import io
import zipfile
import uuid
from datetime import datetime
from typing import List, Optional

import sqlalchemy as sa
from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form, Query
from loguru import logger
from pydantic import BaseModel, field_validator
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.database.models import Employee, Skill, SkillVersion, Tag, Department
from app.services.auth_service import get_current_user, require_admin
from app.utils.text import slugify

router = APIRouter()

# --- Pydantic Models ---

class SkillResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    tags: List[str] = []
    department_id: Optional[uuid.UUID]
    department_name: Optional[str] = None
    current_version: int
    version_hash: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("tags", mode="before")
    @classmethod
    def transform_tags(cls, v):
        if isinstance(v, list):
            return [t.name if hasattr(t, 'name') else t for t in v]
        return v


class SkillListResponse(BaseModel):
    items: List[SkillResponse]
    total: int


class SkillDeleteRequest(BaseModel):
    ids: List[uuid.UUID]


class SkillBulkTagRequest(BaseModel):
    skill_ids: List[uuid.UUID]
    tags: List[str]


class SkillBulkTagSyncRequest(BaseModel):
    skill_ids: List[uuid.UUID]
    add_tags: List[str] = []
    remove_tags: List[str] = []


class SkillBulkDepartmentRequest(BaseModel):
    skill_ids: List[uuid.UUID]
    department_id: Optional[uuid.UUID] = None


class SkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    increment_version: bool = False
    tags: Optional[List[str]] = None


class TagCreateRequest(BaseModel):
    names: List[str]


class TagDeleteRequest(BaseModel):
    names: List[str]


# --- Skill Routes ---

@router.post("/skills/upload")
async def upload_skills(
    files: List[UploadFile] = File(...),
    categories: Optional[str] = Form(None),
    department_id: Optional[uuid.UUID] = Form(None),
    force: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
    _admin: Employee = Depends(require_admin),
):
    """
    Upload one or more ZIP packages containing AI skills.
    
    This endpoint validates the ZIP structure, ensures the mandatory SKILL.md is present,
    checks for duplicate skill names, and enqueues an ingestion task for the worker.

    Args:
        files: List of ZIP files to upload.
        categories: Comma-separated list of tags/categories to assign.
        department_id: UUID of the department owning these skills.
        force: If True, overwrites existing skills with the same name.
        db: Database session.
        current_user: The employee performing the upload.
        _admin: Dependency to ensure only admins can upload.

    Returns:
        A list of results for each file processed (status, version, etc.).
    """
    from app.worker import get_arq_pool
    import hashlib
    
    pool = await get_arq_pool()
    
    tag_names = [c.strip().lower() for c in categories.split(",")] if categories else []
    
    # Pre-fetch or create tags
    tag_objs = []
    if tag_names:
        stmt = select(Tag).where(Tag.name.in_(tag_names))
        res = await db.execute(stmt)
        existing_tags = {t.name: t for t in res.scalars().all()}
        
        for name in tag_names:
            if name in existing_tags:
                tag_objs.append(existing_tags[name])
            else:
                new_tag = Tag(name=name)
                db.add(new_tag)
                tag_objs.append(new_tag)
        await db.flush()

    results = []
    duplicates = []

    try:
        for file in files:
            file_data = await file.read()
            file_hash = hashlib.sha256(file_data).hexdigest()
            name = file.filename.rsplit(".", 1)[0]
            
            # 1. Validate ZIP content: Must have SKILL.md
            try:
                with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                    file_list = [f.filename.lower() for f in zf.infolist()]
                    target_readme = f"{name}/SKILL.md".lower()
                    has_readme = any(
                        f == "skill.md" or 
                        f == target_readme or 
                        f.endswith("/skill.md") 
                        for f in file_list
                    )
                    
                    if not has_readme:
                        results.append({
                            "name": name,
                            "status": "rejected",
                            "message": "Missing SKILL.md file in package."
                        })
                        continue
            except zipfile.BadZipFile:
                results.append({
                    "name": name,
                    "status": "error",
                    "message": "Invalid ZIP file."
                })
                continue

            # 2. Check for existing skill
            stmt = select(Skill).where(Skill.name == name).options(selectinload(Skill.tags))
            res = await db.execute(stmt)
            existing_skill = res.scalars().first()

            if existing_skill:
                if not force:
                    duplicates.append(name)
                    continue
                
                # Update metadata even if hash matches
                if department_id:
                    existing_skill.department_id = department_id
                
                # Merge tags (add if not already present)
                existing_tag_ids = {t.id for t in existing_skill.tags}
                for t in tag_objs:
                    if t.id not in existing_tag_ids:
                        existing_skill.tags.append(t)

                if existing_skill.version_hash == file_hash:
                    results.append({
                        "name": name,
                        "status": "updated_metadata",
                        "message": "Metadata updated, content unchanged."
                    })
                    continue
                
                new_version_num = existing_skill.current_version + 1
                skill_id = existing_skill.id
                existing_skill.status = "processing"
                existing_skill.version_hash = file_hash
            else:
                new_skill = Skill(
                    name=name,
                    slug=slugify(name),
                    status="processing",
                    current_version=1,
                    version_hash=file_hash,
                    tags=tag_objs,
                    department_id=department_id
                )
                db.add(new_skill)
                await db.flush()
                skill_id = new_skill.id
                new_version_num = 1

            new_version = SkillVersion(
                skill_id=skill_id,
                version_number=new_version_num,
                version_hash=file_hash,
                created_by=current_user.id,
            )
            db.add(new_version)
            await db.flush()

            await pool.enqueue_job(
                "ingest_skill_task",
                str(skill_id),
                str(new_version.id),
                file_data,
                file.filename
            )
            
            results.append({
                "name": name,
                "skill_id": str(skill_id),
                "version": new_version_num,
                "status": "processing"
            })

        if duplicates and not force:
            await db.rollback()
            raise HTTPException(
                status_code=409, 
                detail={"message": "Duplicate skill names detected", "duplicates": duplicates}
            )

        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in upload_skills: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"results": results}


@router.post("/skills/{slug}/reupload")
async def reupload_skill(
    slug: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
    _admin: Employee = Depends(require_admin),
):
    """
    Re-upload content for a specific skill to create a new version.

    Args:
        slug: The unique slug or UUID of the skill.
        file: The new ZIP package.
        db: Database session.
        current_user: The employee performing the action.
        _admin: Dependency check.

    Returns:
        The processing status and the new version number.
    """
    from app.worker import get_arq_pool
    import hashlib
    import uuid
    
    # 1. Verify skill exists
    try:
        skill_uuid = uuid.UUID(slug)
        stmt = select(Skill).where(Skill.id == skill_uuid)
    except ValueError:
        stmt = select(Skill).where(Skill.slug == slug)

    res = await db.execute(stmt)
    skill = res.scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    file_data = await file.read()
    file_hash = hashlib.sha256(file_data).hexdigest()
    
    # 2. Validate filename matches skill name
    zip_name = file.filename.rsplit(".", 1)[0]
    if zip_name != skill.name:
        raise HTTPException(
            status_code=400, 
            detail=f"Filename mismatch. Expected '{skill.name}.zip', got '{file.filename}'."
        )

    # 3. Check if content changed
    if skill.version_hash == file_hash:
        return {
            "status": "skipped",
            "message": "Content unchanged. No new version created.",
            "skill_id": str(skill.id),
            "version": skill.current_version
        }

    # 4. Validate ZIP content (Must have SKILL.md)
    try:
        with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
            file_list = [f.filename.lower() for f in zf.infolist()]
            # We use the ZIP's internal name if possible for checking SKILL.md path
            zip_name = file.filename.rsplit(".", 1)[0]
            target_readme = f"{zip_name}/SKILL.md".lower()
            
            has_readme = any(
                f == "skill.md" or 
                f == target_readme or 
                f.endswith("/skill.md") 
                for f in file_list
            )
            
            if not has_readme:
                raise HTTPException(status_code=400, detail="Missing SKILL.md file in package.")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file.")

    # 3. Create new version record
    new_version_num = skill.current_version + 1
    skill.status = "processing"
    skill.version_hash = file_hash # Temporary, worker will re-confirm
    
    new_version = SkillVersion(
        skill_id=skill.id,
        version_number=new_version_num,
        version_hash=file_hash,
        created_by=current_user.id,
    )
    db.add(new_version)
    await db.commit()

    # 4. Enqueue worker task
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "ingest_skill_task",
        str(skill.id),
        str(new_version.id),
        file_data,
        file.filename
    )
    
    return {
        "status": "processing",
        "skill_id": str(skill.id),
        "version": new_version_num
    }


@router.post("/skills/inspect-zip")
async def inspect_skill_zip(
    file: UploadFile = File(...),
    _admin: Employee = Depends(require_admin),
):
    """
    Peek into a ZIP package to extract metadata without saving anything to the database.
    
    This is useful for showing a preview to the user before they confirm the upload.

    Args:
        file: The ZIP package to inspect.
        _admin: Dependency check.

    Returns:
        The skill name and the content of its SKILL.md file.
    """
    import zipfile
    import io
    
    file_data = await file.read()
    name = file.filename.rsplit(".", 1)[0]
    readme_content = ""
    
    try:
        with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
            file_list = [f.filename.lower() for f in zf.infolist()]
            
            # Target is {name}/SKILL.md or just SKILL.md
            target_readme = f"{name}/SKILL.md".lower()
            
            for member in zf.infolist():
                curr = member.filename.lower()
                if curr == "skill.md" or curr == target_readme or curr.endswith("/skill.md"):
                    with zf.open(member) as f:
                        readme_content = f.read().decode("utf-8", errors="ignore")
                    break
                    
        return {
            "name": name,
            "description": readme_content
        }
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file.")
    except Exception as e:
        logger.error(f"Error inspecting zip: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    q: Optional[str] = Query(None),
    tag: Optional[List[str]] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    List and filter skills available in the system.

    Args:
        q: Text search query (matches name and description).
        tag: List of tags to filter by.
        limit: Max results per page.
        offset: Number of records to skip.
        db: Database session.

    Returns:
        A list of skill objects and the total count.
    """
    from sqlalchemy import func
    
    stmt = select(Skill).options(
        selectinload(Skill.department),
        selectinload(Skill.tags)
    ).order_by(Skill.updated_at.desc())
    
    count_stmt = select(func.count()).select_from(Skill)
    
    if q:
        filter_expr = or_(
            Skill.name.ilike(f"%{q}%"),
            Skill.description.ilike(f"%{q}%")
        )
        stmt = stmt.where(filter_expr)
        count_stmt = count_stmt.where(filter_expr)
        
    if tag:
        stmt = stmt.join(Skill.tags).where(Tag.name.in_(tag))
        count_stmt = count_stmt.join(Skill.tags).where(Tag.name.in_(tag))
    
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0
    
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    skills = res.scalars().unique().all()
    
    items = []
    for s in skills:
        resp = SkillResponse.model_validate(s)
        resp.department_name = s.department.name if s.department else None
        items.append(resp)
        
    return {"items": items, "total": total}


@router.delete("/skills/bulk")
async def bulk_delete_skills(
    req: SkillDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Delete multiple skills at once.
    
    Skills are first marked as 'deleting' and then background tasks are
    enqueued to clean up physical storage and database records.

    Args:
        req: List of skill UUIDs to delete.
        db: Database session.

    Returns:
        Confirmation message with the count of queued tasks.
    """
    from app.worker import get_arq_pool
    
    if not req.ids:
        return {"message": "No skills selected"}
        
    pool = await get_arq_pool()
        
    # Mark as deleting first
    stmt = sa.update(Skill).where(Skill.id.in_(req.ids)).values(status="deleting")
    await db.execute(stmt)
    await db.commit()

    # Enqueue tasks
    for skill_id in req.ids:
        await pool.enqueue_job("delete_skill_task", str(skill_id))
        
    return {"message": f"Queued {len(req.ids)} skills for deletion"}


@router.post("/skills/bulk/tags")
async def bulk_add_tags(
    req: SkillBulkTagRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Add a set of tags to multiple skills without removing existing ones.

    Args:
        req: Object containing skill IDs and tag names.
        db: Database session.

    Returns:
        Success message.
    """
    if not req.skill_ids or not req.tags:
        return {"message": "No skills or tags provided"}

    # 1. Get or create tags
    tag_names = [t.strip().lower() for t in req.tags if t.strip()]
    tag_objs = []
    if tag_names:
        stmt = select(Tag).where(Tag.name.in_(tag_names))
        res = await db.execute(stmt)
        existing_tags = {t.name: t for t in res.scalars().all()}
        
        for name in tag_names:
            if name in existing_tags:
                tag_objs.append(existing_tags[name])
            else:
                new_tag = Tag(name=name)
                db.add(new_tag)
                tag_objs.append(new_tag)
        await db.flush()

    # 2. Add tags to each skill
    stmt = select(Skill).where(Skill.id.in_(req.skill_ids)).options(selectinload(Skill.tags))
    res = await db.execute(stmt)
    skills = res.scalars().all()

    for skill in skills:
        existing_tag_names = {t.name for t in skill.tags}
        for tag in tag_objs:
            if tag.name not in existing_tag_names:
                skill.tags.append(tag)
    
    await db.commit()
    return {"message": f"Added tags to {len(skills)} skills"}


@router.post("/skills/bulk/tags/update")
async def bulk_update_tags(
    req: SkillBulkTagSyncRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Perform a bulk update of tags (add and remove) for multiple skills.

    Args:
        req: List of skill IDs and lists of tags to add/remove.
        db: Database session.

    Returns:
        Success message.
    """
    if not req.skill_ids:
        return {"message": "No skills provided"}

    # 1. Prepare tags to add
    tag_objs_to_add = []
    if req.add_tags:
        add_names = [t.strip().lower() for t in req.add_tags if t.strip()]
        if add_names:
            stmt = select(Tag).where(Tag.name.in_(add_names))
            res = await db.execute(stmt)
            existing_tags = {t.name: t for t in res.scalars().all()}
            for name in add_names:
                if name in existing_tags:
                    tag_objs_to_add.append(existing_tags[name])
                else:
                    new_tag = Tag(name=name)
                    db.add(new_tag)
                    tag_objs_to_add.append(new_tag)
            await db.flush()

    # 2. Process removal names
    remove_names = {t.strip().lower() for t in req.remove_tags if t.strip()}

    # 3. Update each skill
    stmt = select(Skill).where(Skill.id.in_(req.skill_ids)).options(selectinload(Skill.tags))
    res = await db.execute(stmt)
    skills = res.scalars().all()

    for skill in skills:
        # Remove tags
        if remove_names:
            skill.tags = [t for t in skill.tags if t.name not in remove_names]
        
        # Add tags
        if tag_objs_to_add:
            existing_tag_names = {t.name for t in skill.tags}
            for tag in tag_objs_to_add:
                if tag.name not in existing_tag_names:
                    skill.tags.append(tag)
    
    await db.commit()
    return {"message": f"Updated tags for {len(skills)} skills"}


@router.post("/skills/bulk/department")
async def bulk_change_department(
    req: SkillBulkDepartmentRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Bulk change the department ownership for a list of skills.

    Args:
        req: Skill IDs and the target department UUID.
        db: Database session.

    Returns:
        Success message.
    """
    if not req.skill_ids:
        return {"message": "No skills provided"}

    stmt = sa.update(Skill).where(Skill.id.in_(req.skill_ids)).values(department_id=req.department_id)
    await db.execute(stmt)
    await db.commit()
    
    return {"message": f"Updated department for {len(req.skill_ids)} skills"}


# --- Tag Routes ---

@router.get("/tags")
async def list_tags(
    q: Optional[str] = Query(None),
    limit: int = Query(1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Retrieve all tags currently stored in the system.

    Args:
        q: Optional search query for tag names.
        limit: Max results.
        offset: Pagination offset.
        db: Database session.

    Returns:
        A list of tag names and total count.
    """
    from sqlalchemy import func
    
    stmt = select(Tag).order_by(Tag.name.asc())
    count_stmt = select(func.count()).select_from(Tag)
    
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q}%"))
        count_stmt = count_stmt.where(Tag.name.ilike(f"%{q}%"))
        
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0
    
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    tags = res.scalars().all()
    
    return {
        "items": [t.name for t in tags],
        "total": total
    }


@router.post("/tags/bulk")
async def bulk_create_tags(
    req: TagCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Create multiple tags in bulk. Skips names that already exist.

    Args:
        req: List of tag names to create.
        db: Database session.

    Returns:
        Count of successfully added new tags.
    """
    names = [n.strip().lower() for n in req.names if n.strip()]
    if not names:
        return {"message": "No valid names provided", "added": 0}
        
    stmt = select(Tag).where(Tag.name.in_(names))
    res = await db.execute(stmt)
    existing_names = {t.name for t in res.scalars().all()}
    
    new_names = [n for n in names if n not in existing_names]
    
    for name in new_names:
        db.add(Tag(name=name))
        
    await db.commit()
    return {"message": f"Added {len(new_names)} new tags", "added": len(new_names)}


@router.delete("/tags/bulk")
async def bulk_delete_tags(
    req: TagDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Permanently delete multiple tags from the system.

    Args:
        req: List of tag names to delete.
        db: Database session.

    Returns:
        Success message.
    """
    from sqlalchemy import delete
    
    if not req.names:
        return {"message": "No tags selected"}
        
    stmt = delete(Tag).where(Tag.name.in_(req.names))
    await db.execute(stmt)
    await db.commit()
    return {"message": f"Deleted {len(req.names)} tags"}


@router.get("/skills/tags")
async def get_all_tags(
    db: AsyncSession = Depends(get_db),
    _user: Employee = Depends(get_current_user),
):
    """
    Get all unique tags used across all skills.

    Args:
        db: Database session.

    Returns:
        List of Tag objects.
    """
    stmt = select(Tag).order_by(Tag.name)
    res = await db.execute(stmt)
    return res.scalars().all()


# --- Individual Skill Routes (MUST BE LAST) ---

@router.get("/skills/{slug}", response_model=SkillResponse)
async def get_skill(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _current_user: Employee = Depends(get_current_user),
):
    """
    Get detailed information for a single skill.

    Args:
        slug: The skill's slug string or UUID.
        db: Database session.

    Returns:
        Detailed skill response including tags and department.
    """
    import uuid
    logger.info(f"Fetching skill with identifier: {slug}")
    try:
        skill_uuid = uuid.UUID(slug)
        stmt = select(Skill).where(Skill.id == skill_uuid)
    except ValueError:
        logger.info(f"Searching by slug: {slug}")
        stmt = select(Skill).where(Skill.slug == slug)

    stmt = stmt.options(
        selectinload(Skill.department),
        selectinload(Skill.tags)
    )
    res = await db.execute(stmt)
    skill = res.scalars().first()
    if not skill:
        logger.warning(f"Skill not found for identifier: {identifier}")
        raise HTTPException(status_code=404, detail="Skill not found")
    
    resp = SkillResponse.model_validate(skill)
    resp.department_name = skill.department.name if skill.department else None
    return resp


@router.delete("/skills/{slug}")
async def delete_skill(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Delete a single skill by its identifier.

    Args:
        slug: The skill's slug string or UUID.
        db: Database session.

    Returns:
        Confirmation message.
    """
    from app.worker import get_arq_pool
    import uuid
    try:
        skill_uuid = uuid.UUID(slug)
        stmt = select(Skill).where(Skill.id == skill_uuid)
    except ValueError:
        stmt = select(Skill).where(Skill.slug == slug)

    res = await db.execute(stmt)
    skill = res.scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    pool = await get_arq_pool()

    skill.status = "deleting"
    await db.commit()

    await pool.enqueue_job("delete_skill_task", str(skill.id))
    return {"message": "Skill marked for deletion"}


@router.patch("/skills/{slug}", response_model=SkillResponse)
async def update_skill(
    slug: str,
    req: SkillUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Employee = Depends(require_admin),
):
    """
    Update a skill's metadata or documentation content.

    Args:
        slug: The skill's slug string or UUID.
        req: Fields to update (name, description, department, tags).
        db: Database session.

    Returns:
        The updated skill object.
    """
    from app.services.storage_service import storage_service
    import uuid
    
    try:
        skill_uuid = uuid.UUID(slug)
        stmt = select(Skill).where(Skill.id == skill_uuid)
    except ValueError:
        stmt = select(Skill).where(Skill.slug == slug)

    stmt = stmt.options(
        selectinload(Skill.department),
        selectinload(Skill.tags)
    )
    res = await db.execute(stmt)
    skill = res.scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # 1. Update basic fields
    if req.name is not None and req.name != skill.name:
        # Check if another skill already has this name
        stmt = select(Skill).where(Skill.name == req.name, Skill.id != skill.id)
        res = await db.execute(stmt)
        if res.scalars().first():
            raise HTTPException(status_code=409, detail=f"Skill with name '{req.name}' already exists.")
        skill.name = req.name
        skill.slug = slugify(req.name) # Update slug when name changes
    
    # 2. Update description and physical SKILL.md in MinIO
    # 2. Update description (documentation) and handle versioning
    if req.description is not None and req.description != skill.description:
        if req.increment_version:
            # Increment version number
            new_version_num = skill.current_version + 1
            
            # Recalculate hash for the new documentation content
            import hashlib
            content_hash = hashlib.sha256(req.description.encode()).hexdigest()
            skill.version_hash = content_hash
            
            # Create new version record in DB
            new_v = SkillVersion(
                skill_id=skill.id,
                version_number=new_version_num,
                changelog="Manual update via UI",
                # New storage path for the new version
                storage_path=f"skills/{skill.id}/versions/{new_version_num}/content/"
            )
            db.add(new_v)
            
            # Update skill metadata
            skill.current_version = new_version_num
            skill.storage_path = new_v.storage_path
            
        skill.description = req.description
        
        if skill.storage_path:
            # Overwrite SKILL.md in the (potentially new) storage path
            base_path = skill.storage_path.rstrip("/")
            object_name = f"{base_path}/SKILL.md"
            storage_service.upload_file(
                object_name=object_name,
                data=req.description.encode("utf-8"),
                content_type="text/markdown"
            )
            logger.info(f"Updated physical file: {object_name}")

    # 3. Update Department
    if req.department_id is not None:
        # Verify department exists
        stmt = select(Department).where(Department.id == req.department_id)
        res = await db.execute(stmt)
        if not res.scalars().first():
            raise HTTPException(status_code=404, detail="Department not found")
        skill.department_id = req.department_id
    elif "department_id" in req.model_fields_set and req.department_id is None:
        skill.department_id = None

    # 4. Update Tags
    if req.tags is not None:
        tag_names = [t.strip().lower() for t in req.tags if t.strip()]
        tag_objs = []
        if tag_names:
            stmt = select(Tag).where(Tag.name.in_(tag_names))
            res = await db.execute(stmt)
            existing_tags = {t.name: t for t in res.scalars().all()}
            
            for name in tag_names:
                if name in existing_tags:
                    tag_objs.append(existing_tags[name])
                else:
                    new_tag = Tag(name=name)
                    db.add(new_tag)
                    tag_objs.append(new_tag)
            await db.flush()
        
        skill.tags = tag_objs

    await db.commit()
    await db.refresh(skill)

    resp = SkillResponse.model_validate(skill)
    resp.department_name = skill.department.name if skill.department else None
    return resp

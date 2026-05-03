"""
arq Worker — async Redis queue for document ingestion.

The worker now compiles each source into the LLM Wiki (markdown pages stored
in PostgreSQL) instead of producing chunk embeddings. See app/ai/wiki_compiler.py.

Start with:
    arq app.worker.WorkerSettings
"""

import io
import uuid
import zipfile
from typing import Callable, Optional

from arq import cron
from arq.connections import RedisSettings, ArqRedis, create_pool
from loguru import logger

from app.config import settings


def _get_redis_settings() -> RedisSettings:
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        database=settings.redis_db,
        password=settings.redis_password or None,
    )


# arq Redis pool (lazy init)
_arq_pool: Optional[ArqRedis] = None


async def get_arq_pool() -> ArqRedis:
    """Lazy-init arq Redis connection pool."""
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(_get_redis_settings())
    return _arq_pool


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------

class ProgressTracker:
    """Updates source.progress + source.progress_message in DB."""

    def __init__(self, source_id: uuid.UUID):
        self.source_id = source_id

    async def update(self, progress: int, message: str):
        from app.database import async_session_factory
        from app.database.models import Source
        async with async_session_factory() as session:
            source = await session.get(Source, self.source_id)
            if source:
                source.progress = progress
                source.progress_message = message
                await session.commit()
        logger.debug(f"[{self.source_id}] Progress: {progress}% — {message}")


# ---------------------------------------------------------------------------
# Ingestion tasks
# ---------------------------------------------------------------------------

async def ingest_file_task(ctx: dict, source_id: str):
    """
    arq task: full file ingestion → wiki compilation.
    Steps: download from MinIO → extract text → vision captions → outline → compile wiki.
    File must already be uploaded to MinIO before this task is enqueued.
    """
    from app.database import async_session_factory
    from app.database.models import KnowledgeType, Source
    from app.ai.registry import ProviderRegistry
    from app.ai.wiki_agent import compile_source_with_agent
    from app.services.image_service import extract_images
    from app.services.source_outline import assemble_full_text, build_outline
    from app.services.storage_service import storage_service
    from app.services.kb_service import (
        _extract_text_from_file,
        _inline_image_captions,
    )

    sid = uuid.UUID(source_id)
    tracker = ProgressTracker(sid)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            raise ValueError(f"Source {source_id} not found")
        if not source.minio_key:
            raise ValueError(f"Source {source_id} has no file in storage")

        file_name = source.file_name or source.minio_key.split("/")[-1]

        try:
            source.status = "processing"
            source.progress = 0
            source.progress_message = "Starting processing..."
            await session.commit()

            # --- Step 1: Download from MinIO (10%) ---
            await tracker.update(5, "Loading file...")
            file_data = storage_service.download_file(source.minio_key)
            await tracker.update(10, "File loaded")

            # --- Step 2: Extract text per page (25%) ---
            await tracker.update(15, "Extracting text (per page)...")
            pages_data = await _extract_text_from_file(file_data, file_name)

            if not pages_data or not any((p.get("content") or "").strip() for p in pages_data):
                source.status = "error"
                source.error_message = "Unable to extract text content"
                source.progress = 0
                await session.commit()
                return {"status": "error", "message": "No text content"}

            await tracker.update(25, "Text extraction complete")

            # --- Step 3: Extract images + vision captions (40%) ---
            await tracker.update(30, "Extracting and analyzing images...")
            images = extract_images(file_data, file_name, source_id)

            registry = ProviderRegistry(session)
            vision_provider = await registry.get_vision()
            if vision_provider and images:
                for idx, img in enumerate(images, 1):
                    try:
                        if idx % 5 == 0 or idx == 1 or idx == len(images):
                            logger.info(f"Vision AI analyzing image {idx}/{len(images)}...")
                        img_bytes = storage_service.download_file(img.minio_key)
                        mime_type = "image/png" if img.minio_key.lower().endswith(".png") else "image/jpeg"
                        img.caption = await vision_provider.analyze_image(img_bytes, mime_type)
                    except Exception as e:
                        logger.warning(f"Failed to analyze image {img.minio_key}: {e}")
            elif images:
                logger.info("No vision provider configured, skipping image captioning")

            # Inline captions into per-page text so the compiler sees them.
            _inline_image_captions(pages_data, images)
            await tracker.update(40, f"Analyzed {len(images)} images")

            # --- Step 4: Build outline + assemble full_text (50%) ---
            await tracker.update(45, "Building document outline...")
            source.outline_json = build_outline(pages_data)
            full_text, page_offsets = assemble_full_text(pages_data)
            source.full_text = full_text
            source.page_offsets = page_offsets
            await session.commit()
            await tracker.update(50, f"Outline: {len(source.outline_json or [])} top-level sections")

            # --- Step 5: Resolve KnowledgeType context (52%) ---
            kt_slug = kt_name = kt_desc = None
            if source.knowledge_type_id:
                kt = await session.get(KnowledgeType, source.knowledge_type_id)
                if kt:
                    kt_slug, kt_name, kt_desc = kt.slug, kt.name, kt.description

            # --- Step 6: Compile into wiki via mini-agent (55-95%) ---
            await tracker.update(55, "Compiling into wiki (agent)...")

            async def emit(step: int, message: str) -> None:
                progress = min(95, 55 + step)
                await tracker.update(progress, f"Compiling: {message}")

            result = await compile_source_with_agent(
                session=session,
                source=source,
                full_text=full_text,
                kt_slug=kt_slug,
                kt_name=kt_name,
                kt_desc=kt_desc,
                on_progress=emit,
            )
            await session.commit()
            await tracker.update(
                95,
                f"Wiki: +{result['pages_created']} pages, ~{result['pages_updated']} updated "
                f"({result['tool_calls']} tool calls)",
            )

            # --- Done (100%) ---
            source.status = "ready"
            source.progress = 100
            source.progress_message = "Done"
            source.error_message = None
            await session.commit()

            logger.success(
                f"Source {source_id} ingested: {len(images)} images, "
                f"+{result['pages_created']} pages, ~{result['pages_updated']} updated"
            )
            return {
                "status": "ready",
                "images": len(images),
                "pages_created": result["pages_created"],
                "pages_updated": result["pages_updated"],
            }

        except Exception as e:
            logger.error(f"Ingestion failed for {source_id}: {e}")
            source.status = "error"
            source.error_message = str(e)[:500]
            source.progress = 0
            source.progress_message = f"Error: {str(e)[:200]}"
            await session.commit()
            raise


async def ingest_url_task(ctx: dict, source_id: str):
    """arq task: URL ingestion → wiki compilation."""
    from app.database import async_session_factory
    from app.database.models import KnowledgeType, Source
    from app.ai.wiki_agent import compile_source_with_agent
    from app.services.kb_service import _extract_text_from_url
    from app.services.source_outline import assemble_full_text, build_outline

    sid = uuid.UUID(source_id)
    tracker = ProgressTracker(sid)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        try:
            source.status = "processing"
            source.progress = 0
            await session.commit()

            await tracker.update(15, "Fetching content from URL...")
            if not source.url:
                source.status = "error"
                source.error_message = "Source has no URL"
                await session.commit()
                return {"status": "error"}
            pages_data = await _extract_text_from_url(source.url)

            if not pages_data or not any((p.get("content") or "").strip() for p in pages_data):
                source.status = "error"
                source.error_message = "Unable to fetch content from URL"
                await session.commit()
                return {"status": "error"}

            await tracker.update(40, "Building outline...")
            source.outline_json = build_outline(pages_data)
            full_text, page_offsets = assemble_full_text(pages_data)
            source.full_text = full_text
            source.page_offsets = page_offsets
            await session.commit()

            kt_slug = kt_name = kt_desc = None
            if source.knowledge_type_id:
                kt = await session.get(KnowledgeType, source.knowledge_type_id)
                if kt:
                    kt_slug, kt_name, kt_desc = kt.slug, kt.name, kt.description

            await tracker.update(55, "Compiling into wiki (agent)...")

            async def emit(step: int, message: str) -> None:
                progress = min(95, 55 + step)
                await tracker.update(progress, f"Compiling: {message}")

            result = await compile_source_with_agent(
                session=session,
                source=source,
                full_text=full_text,
                kt_slug=kt_slug,
                kt_name=kt_name,
                kt_desc=kt_desc,
                on_progress=emit,
            )
            await session.commit()

            source.status = "ready"
            source.progress = 100
            source.progress_message = "Done"
            source.error_message = None
            await session.commit()

            logger.success(
                f"URL source {source_id} ingested: "
                f"+{result['pages_created']} pages, ~{result['pages_updated']} updated"
            )
            return {
                "status": "ready",
                "pages_created": result["pages_created"],
                "pages_updated": result["pages_updated"],
            }

        except Exception as e:
            logger.error(f"URL ingestion failed for {source_id}: {e}")
            source.status = "error"
            source.error_message = str(e)[:500]
            source.progress = 0
            await session.commit()
            raise


async def reingest_file_task(ctx: dict, source_id: str, force: bool = False):
    """
    arq task: re-ingest a file already stored in MinIO.

    If `force=True`, detach this source from all wiki pages first (orphan
    pages get deleted). Otherwise the compiler will merge new ops on top of
    the existing wiki state.
    """
    from app.database import async_session_factory
    from app.database.models import Source
    from app.services import wiki_service

    sid = uuid.UUID(source_id)

    async with async_session_factory() as session:
        source = await session.get(Source, sid)
        if not source or not source.minio_key:
            raise ValueError(f"Source {source_id} not found or has no file")

        if force:
            await wiki_service.detach_source_from_wiki(session, sid)
            await wiki_service.regenerate_index(session)
            await session.commit()

    await ingest_file_task(ctx, source_id)


# ---------------------------------------------------------------------------
# Worker configuration
# ---------------------------------------------------------------------------


async def ingest_skill_task(ctx: dict, skill_id: str, version_id: str, file_data: bytes, file_name: str):
    """
    arq task: unzip skill package, store in MinIO, and extract metadata.
    """
    from app.database import async_session_factory
    from app.database.models import Skill, SkillVersion
    from app.services.storage_service import storage_service

    sid = uuid.UUID(skill_id)
    vid = uuid.UUID(version_id)
    skill_name = file_name.rsplit(".", 1)[0]
    
    logger.info(f"Starting ingestion for skill: {skill_name} ({skill_id})")

    async with async_session_factory() as session:
        skill = await session.get(Skill, sid)
        version = await session.get(SkillVersion, vid)
        
        if not skill or not version:
            logger.error(f"Skill {skill_id} or Version {version_id} not found in DB")
            return

        try:
            skill.status = "processing"
            await session.commit()

            # 1. Unzip and upload to MinIO
            readme_content = None
            with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    
                    with zf.open(member) as f:
                        content = f.read()
                        
                        # Define MinIO key: skills/{id}/versions/{v}/content/{path}
                        object_name = f"skills/{skill_id}/versions/{version.version_number}/content/{member.filename}"
                        
                        # Guess content type
                        from app.services.kb_service import _guess_content_type
                        storage_service.upload_file(
                            object_name=object_name,
                            data=content,
                            content_type=_guess_content_type(member.filename)
                        )

                        # Check for SKILL.md
                        # User said it's inside a folder with the same name: {skill_name}/SKILL.md
                        target_readme = f"{skill_name}/SKILL.md".lower()
                        if member.filename.lower() == target_readme or member.filename.lower().endswith("/skill.md"):
                            readme_content = content.decode("utf-8", errors="ignore")
                            logger.info(f"Found SKILL.md in {member.filename}")

            # 2. Update DB with extracted metadata
            if readme_content:
                skill.description = readme_content
                version.readme = readme_content
            
            # Store hash (calculated in API but re-confirming here)
            import hashlib
            file_hash = hashlib.sha256(file_data).hexdigest()
            
            skill.version_hash = file_hash
            skill.current_version = version.version_number
            skill.storage_path = f"skills/{skill_id}/versions/{version.version_number}/content/"
            skill.status = "active"
            
            version.version_hash = file_hash
            version.storage_path = skill.storage_path
            
            await session.commit()
            logger.success(f"Skill {skill_name} version {version.version_number} processed successfully")

        except Exception as e:
            logger.exception(f"Failed to process skill {skill_name}: {e}")
            skill.status = "error"
            await session.commit()


async def delete_skill_task(ctx: dict, skill_id: str):
    """
    arq task: delete skill files from MinIO and remove from DB.
    """
    from app.database import async_session_factory
    from app.database.models import Skill
    from app.services.storage_service import storage_service

    sid = uuid.UUID(skill_id)
    
    logger.info(f"Starting deletion task for skill: {skill_id}")

    async with async_session_factory() as session:
        skill = await session.get(Skill, sid)
        if not skill:
            logger.warning(f"Skill {skill_id} already deleted or not found")
            return

        try:
            # 1. Delete files from MinIO (prefix: skills/{skill_id}/)
            prefix = f"skills/{skill_id}/"
            storage_service.delete_prefix(prefix)
            
            # 2. Delete skill from DB (cascades to SkillVersion if configured, 
            # but let's be explicit if needed or trust the model relationship)
            await session.delete(skill)
            await session.commit()
            
            logger.success(f"Skill {skill_id} and all assets deleted successfully")

        except Exception as e:
            logger.exception(f"Failed to delete skill {skill_id}: {e}")
            raise


class WorkerSettings:
    """arq worker configuration."""

    functions = [ingest_file_task, ingest_url_task, reingest_file_task, ingest_skill_task, delete_skill_task]
    redis_settings = _get_redis_settings()
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    max_tries = 3
    retry_delay = 10
    health_check_interval = 30

    @staticmethod
    async def on_startup(ctx: dict):
        logger.info("arq worker started — listening for ingestion jobs...")

    @staticmethod
    async def on_shutdown(ctx: dict):
        logger.info("arq worker shutting down...")

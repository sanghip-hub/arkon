"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Contact } from "./contact-table";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contact: Contact | null;
  onSaved: () => void;
};

export function ContactDialog({ open, onOpenChange, contact, onSaved }: Props) {
  const isEdit = !!contact;
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [topicsRaw, setTopicsRaw] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (contact) {
      setName(contact.name);
      setRole(contact.role || "");
      setEmail(contact.email || "");
      setPhone(contact.phone || "");
      setTopicsRaw(contact.topics?.join(", ") || "");
      setNote(contact.note || "");
    } else {
      setName("");
      setRole("");
      setEmail("");
      setPhone("");
      setTopicsRaw("");
      setNote("");
    }
    setError("");
  }, [contact, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");

    const topics = topicsRaw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    const body = {
      name,
      role: role || null,
      email: email || null,
      phone: phone || null,
      topics: topics.length > 0 ? topics : null,
      note: note || null,
    };

    try {
      if (isEdit) {
        await api(`/api/contacts/${contact.id}`, { method: "PUT", body });
      } else {
        await api("/api/contacts", { method: "POST", body });
      }
      onSaved();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-xl">
            {isEdit ? "Edit Contact" : "Add Contact"}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 mt-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="c-name">Name</Label>
            <Input
              id="c-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="bg-background"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="c-role">Role / Title</Label>
              <Input
                id="c-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                placeholder="e.g. Sales Manager"
                className="bg-background"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="c-phone">Phone</Label>
              <Input
                id="c-phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+84 ..."
                className="bg-background"
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="c-email">Email</Label>
            <Input
              id="c-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-background"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="c-topics">Topics (comma-separated)</Label>
            <Input
              id="c-topics"
              value={topicsRaw}
              onChange={(e) => setTopicsRaw(e.target.value)}
              placeholder="e.g. contracts, legal, compliance"
              className="bg-background"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="c-note">Note</Label>
            <Input
              id="c-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Brief description..."
              className="bg-background"
            />
          </div>

          {error && (
            <p className="text-destructive text-sm bg-destructive/10 px-3 py-2 rounded-lg">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 mt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={saving}
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {saving ? "Saving..." : isEdit ? "Update" : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

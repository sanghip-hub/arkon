"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { ContactTable, type Contact } from "@/components/contacts/contact-table";
import { ContactDialog } from "@/components/contacts/contact-dialog";

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editContact, setEditContact] = useState<Contact | null>(null);

  const loadContacts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<Contact[]>("/api/contacts");
      setContacts(data);
    } catch {
      setContacts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadContacts();
  }, [loadContacts]);

  const handleCreate = () => {
    setEditContact(null);
    setDialogOpen(true);
  };

  const handleEdit = (contact: Contact) => {
    setEditContact(contact);
    setDialogOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Contacts"
        description="Directory of contacts available for AI lookup."
        action={
          <Button
            onClick={handleCreate}
            className="bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <span className="material-symbols-outlined text-base mr-1">
              person_add
            </span>
            Add Contact
          </Button>
        }
      />

      <ContactTable
        contacts={contacts}
        loading={loading}
        onEdit={handleEdit}
        onRefresh={loadContacts}
      />

      <ContactDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        contact={editContact}
        onSaved={loadContacts}
      />
    </>
  );
}

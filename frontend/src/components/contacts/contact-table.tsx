"use client";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/shared/empty-state";

export type Contact = {
  id: string;
  name: string;
  role?: string;
  phone?: string;
  email?: string;
  topics?: string[];
  note?: string;
};

type Props = {
  contacts: Contact[];
  loading: boolean;
  onEdit: (contact: Contact) => void;
  onRefresh: () => void;
};

export function ContactTable({ contacts, loading, onEdit, onRefresh }: Props) {
  const handleDelete = async (id: string) => {
    if (!confirm("Delete this contact? This cannot be undone.")) return;
    try {
      await api(`/api/contacts/${id}`, { method: "DELETE" });
      onRefresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete contact");
    }
  };

  if (loading) {
    return (
      <div className="bg-card rounded-xl border border-border shadow-sahara flex items-center justify-center py-16">
        <span className="material-symbols-outlined text-3xl text-muted-foreground animate-spin">
          progress_activity
        </span>
      </div>
    );
  }

  if (contacts.length === 0) {
    return (
      <div className="bg-card rounded-xl border border-border shadow-sahara">
        <EmptyState
          icon="contacts"
          title="No contacts"
          description="Add contacts to make them searchable by AI"
        />
      </div>
    );
  }

  return (
    <div className="bg-card rounded-xl border border-border shadow-sahara overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="text-xs uppercase tracking-wider">Name</TableHead>
            <TableHead className="text-xs uppercase tracking-wider">Role</TableHead>
            <TableHead className="text-xs uppercase tracking-wider">Email</TableHead>
            <TableHead className="text-xs uppercase tracking-wider">Phone</TableHead>
            <TableHead className="text-xs uppercase tracking-wider">Topics</TableHead>
            <TableHead className="text-xs uppercase tracking-wider text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {contacts.map((contact) => (
            <TableRow key={contact.id} className="hover:bg-secondary/30">
              <TableCell>
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-xs font-bold shrink-0">
                    {contact.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{contact.name}</p>
                    {contact.note && (
                      <p className="text-xs text-muted-foreground truncate max-w-48">{contact.note}</p>
                    )}
                  </div>
                </div>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {contact.role || "—"}
              </TableCell>
              <TableCell className="text-sm">
                {contact.email ? (
                  <a href={`mailto:${contact.email}`} className="hover:underline text-primary">
                    {contact.email}
                  </a>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {contact.phone || "—"}
              </TableCell>
              <TableCell>
                {contact.topics && contact.topics.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {contact.topics.slice(0, 3).map((t) => (
                      <span
                        key={t}
                        className="text-xs bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full"
                      >
                        {t}
                      </span>
                    ))}
                    {contact.topics.length > 3 && (
                      <span className="text-xs text-muted-foreground">
                        +{contact.topics.length - 3}
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="text-muted-foreground text-sm">—</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger className="inline-flex items-center justify-center h-8 w-8 rounded-md hover:bg-accent hover:text-accent-foreground">
                    <span className="material-symbols-outlined text-base">more_vert</span>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => onEdit(contact)}>
                      <span className="material-symbols-outlined text-base mr-2">edit</span>
                      Edit
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => handleDelete(contact.id)}
                      className="text-destructive"
                    >
                      <span className="material-symbols-outlined text-base mr-2">delete</span>
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

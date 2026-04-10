# Copyright (c) 2025, Rl0007 and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils.data import cint


class DeleteDocumentData(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from delete_docs.delete_docs.doctype.delete_document_item.delete_document_item import DeleteDocumentItem

		auto_order_dependencies: DF.Check
		batch_size: DF.Int
		delete_child_tables: DF.Check
		documents: DF.Table[DeleteDocumentItem]
		skip_hooks: DF.Check
		workers: DF.Int
	# end: auto-generated types

	@frappe.whitelist()
	def fetch_counts(self):
		for row in self.documents:
			row.document_count = frappe.db.count(row.document)
			row.status = "Pending"
		self.save()

	@frappe.whitelist()
	def bulk_delete_documents(self):
		doctypes = [row.document for row in self.documents]
		if not doctypes:
			frappe.throw("Please add at least one DocType to delete.")

		if self.auto_order_dependencies:
			doctypes = order_by_dependencies(doctypes)

		frappe.enqueue(
			run_bulk_delete,
			doctypes=doctypes,
			skip_hooks=cint(self.skip_hooks),
			delete_child_tables=cint(self.delete_child_tables),
			batch_size=self.batch_size or 1000,
			workers=cint(self.workers) or 4,
			queue="long",
			timeout=36000,
		)
		frappe.msgprint(
			f"Bulk delete queued for {len(doctypes)} DocType(s) in the background.",
			alert=True,
		)


def order_by_dependencies(doctypes):
	"""Reorder doctypes so that child/linked doctypes are deleted before parents."""
	doctype_set = set(doctypes)
	dependency_map = {}

	for doctype in doctypes:
		meta = frappe.get_meta(doctype)
		depends_on = set()
		for field in meta.fields:
			if field.fieldtype == "Link" and field.options in doctype_set and field.options != doctype:
				depends_on.add(field.options)
		dependency_map[doctype] = depends_on

	# Topological sort — delete dependents first, then parents
	ordered = []
	visited = set()

	def visit(doctype):
		if doctype in visited:
			return
		visited.add(doctype)
		for dependency in dependency_map.get(doctype, []):
			visit(dependency)
		ordered.append(doctype)

	for doctype in doctypes:
		visit(doctype)

	# Reverse: we want leaf doctypes (no dependents) deleted first
	ordered.reverse()
	return ordered


def get_child_tables(doctype):
	"""Return list of child table DocType names for a given parent DocType."""
	meta = frappe.get_meta(doctype)
	child_tables = []
	for field in meta.fields:
		if field.fieldtype in ("Table", "Table MultiSelect"):
			child_tables.append(field.options)
	return child_tables


def run_bulk_delete(doctypes, skip_hooks, delete_child_tables, batch_size, workers):
	"""Process deletion for each DocType sequentially (in dependency order)."""
	for doctype in doctypes:
		frappe.publish_realtime(
			"bulk_delete_progress",
			{"doctype": doctype, "status": "Deleting"},
		)

		try:
			if skip_hooks:
				delete_direct(doctype, delete_child_tables)
			else:
				delete_with_hooks(doctype, batch_size, workers)

			frappe.publish_realtime(
				"bulk_delete_progress",
				{"doctype": doctype, "status": "Completed"},
			)
		except Exception as e:
			frappe.log_error(f"Bulk delete error for {doctype}: {e}")
			frappe.publish_realtime(
				"bulk_delete_progress",
				{"doctype": doctype, "status": "Error", "error": str(e)},
			)

	frappe.publish_realtime("bulk_delete_complete", {"doctypes": doctypes})


def delete_direct(doctype, delete_child_tables):
	"""Fast path: direct DB delete, no hooks."""
	if delete_child_tables:
		for child_table in get_child_tables(doctype):
			frappe.db.delete(child_table, {"parenttype": doctype})

	frappe.db.delete(doctype)
	frappe.db.commit()


def delete_with_hooks(doctype, batch_size, workers):
	"""Slow path: uses frappe.delete_doc so hooks run. Parallelized across workers."""
	all_names = frappe.get_all(doctype, pluck="name")
	if not all_names:
		return

	# Split names across workers
	chunks = [[] for _ in range(workers)]
	for index, name in enumerate(all_names):
		chunks[index % workers].append(name)

	for worker_index, chunk in enumerate(chunks):
		if not chunk:
			continue
		frappe.enqueue(
			delete_document_chunk,
			doctype=doctype,
			names=chunk,
			batch_size=batch_size,
			worker_index=worker_index,
			queue="long",
			timeout=36000,
		)


def delete_document_chunk(doctype, names, batch_size, worker_index):
	"""Worker function: deletes a chunk of documents."""
	deleted = 0
	frappe.flags.in_bulk_delete = True

	for name in names:
		try:
			frappe.delete_doc(doctype, name, force=True)
			deleted += 1
		except Exception as e:
			frappe.log_error(f"Error deleting {doctype} {name}: {e}")

		if deleted % batch_size == 0:
			frappe.db.commit()
			frappe.publish_realtime(
				"bulk_delete_progress",
				{"doctype": doctype, "deleted": deleted, "worker": worker_index},
			)

	frappe.db.commit()

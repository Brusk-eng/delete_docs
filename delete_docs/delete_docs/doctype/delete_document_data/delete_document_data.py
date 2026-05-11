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
		cancel_before_delete: DF.Check
		delete_child_tables: DF.Check
		documents: DF.Table[DeleteDocumentItem]
		include_connected_docs: DF.Check
		skip_hooks: DF.Check
		workers: DF.Int
	# end: auto-generated types

	@frappe.whitelist()
	def fetch_counts(self):
		for row in self.documents:
			filters = row_filters(row)
			row.document_count = frappe.db.count(row.document, filters=filters or None)
			row.status = "Pending"
		self.save()

	@frappe.whitelist()
	def bulk_delete_documents(self):
		doctypes = [row.document for row in self.documents]
		if not doctypes:
			frappe.throw("Please add at least one DocType to delete.")

		filters_by_doctype = {
			row.document: row_filters(row)
			for row in self.documents
			if row_filters(row)
		}

		if self.include_connected_docs:
			doctypes = discover_connected_doctypes(doctypes)

		if self.auto_order_dependencies:
			doctypes = order_by_dependencies(doctypes)

		frappe.enqueue(
			run_bulk_delete,
			doctypes=doctypes,
			filters_by_doctype=filters_by_doctype,
			skip_hooks=cint(self.skip_hooks),
			delete_child_tables=cint(self.delete_child_tables),
			cancel_before_delete=cint(self.cancel_before_delete),
			batch_size=self.batch_size or 1000,
			workers=cint(self.workers) or 4,
			queue="long",
			timeout=36000,
		)
		frappe.msgprint(
			f"Bulk delete queued for {len(doctypes)} DocType(s) in the background.",
			alert=True,
		)


def row_filters(row):
	"""Return a {fieldname: value} dict for the row, or empty dict if no filter set."""
	if not row.filter_field:
		return {}
	return {row.filter_field: row.filter_value}


def discover_connected_doctypes(doctypes):
	"""Discover all submittable doctypes that have links to the given doctypes.

	For example, if 'Sales Order' is given, this will find 'Delivery Note',
	'Sales Invoice', 'Purchase Order', etc. that reference Sales Order.
	"""
	doctype_set = set(doctypes)
	discovered = set(doctypes)
	to_process = list(doctypes)

	while to_process:
		current = to_process.pop(0)
		linked_doctypes = find_linked_doctypes(current)
		for linked_dt in linked_doctypes:
			if linked_dt not in discovered:
				discovered.add(linked_dt)
				to_process.append(linked_dt)

	return list(discovered)


def find_linked_doctypes(doctype):
	"""Find all doctypes that have Link or Dynamic Link fields pointing to this doctype."""
	linked = set()

	system_doctypes = [
		"DocType", "DocField", "DocPerm", "DocType Link",
		"DocType Action", "DocType State", "Custom Field", "Property Setter",
	]

	# Find doctypes with Link fields pointing to this doctype
	link_fields = frappe.get_all(
		"DocField",
		filters={
			"fieldtype": "Link",
			"options": doctype,
			"parent": ["not in", system_doctypes],
		},
		fields=["parent"],
		distinct=True,
	)

	for field in link_fields:
		parent_dt = field.parent
		if is_submittable(parent_dt) and not is_child_table(parent_dt):
			linked.add(parent_dt)

	# Find doctypes with Dynamic Link fields that could point to this doctype
	dynamic_link_fields = frappe.get_all(
		"DocField",
		filters={
			"fieldtype": "Dynamic Link",
			"parent": ["not in", system_doctypes],
		},
		fields=["parent", "options"],
		distinct=True,
	)

	for field in dynamic_link_fields:
		parent_dt = field.parent
		if is_child_table(parent_dt) or not is_submittable(parent_dt):
			continue
		# Check if any record of this doctype actually references our target doctype
		# field.options is the fieldname that holds the doctype name
		exists = frappe.db.exists(parent_dt, {field.options: doctype})
		if exists:
			linked.add(parent_dt)

	return linked


def is_submittable(doctype):
	"""Check if a doctype is submittable."""
	return cint(frappe.db.get_value("DocType", doctype, "is_submittable"))


def is_child_table(doctype):
	"""Check if a doctype is a child table."""
	return cint(frappe.db.get_value("DocType", doctype, "istable"))


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


def run_bulk_delete(doctypes, filters_by_doctype, skip_hooks, delete_child_tables, cancel_before_delete, batch_size, workers):
	"""Process deletion for each DocType sequentially (in dependency order)."""
	filters_by_doctype = filters_by_doctype or {}
	for doctype in doctypes:
		filters = filters_by_doctype.get(doctype) or {}
		frappe.publish_realtime(
			"bulk_delete_progress",
			{"doctype": doctype, "status": "Deleting"},
		)

		try:
			if cancel_before_delete and is_submittable(doctype):
				cancel_submitted_docs(doctype, batch_size, filters=filters)

			if skip_hooks:
				delete_direct(doctype, delete_child_tables, filters=filters)
			elif cancel_before_delete:
				# When cancel_before_delete is on, we must delete synchronously
				# to ensure each doctype is fully deleted before moving to the next.
				# Otherwise async workers return immediately and the next doctype
				# fails with LinkExistsError.
				delete_with_hooks_sync(doctype, batch_size, filters=filters)
			else:
				delete_with_hooks(doctype, batch_size, workers, filters=filters)

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


def cancel_submitted_docs(doctype, batch_size, filters=None):
	"""Cancel all submitted documents (docstatus=1) of the given doctype."""
	cancel_filters = {"docstatus": 1, **(filters or {})}
	submitted_docs = frappe.get_all(
		doctype,
		filters=cancel_filters,
		pluck="name",
	)

	if not submitted_docs:
		return

	frappe.publish_realtime(
		"bulk_delete_progress",
		{"doctype": doctype, "status": "Cancelling", "total": len(submitted_docs)},
	)

	cancelled = 0
	frappe.flags.in_bulk_delete = True

	for name in submitted_docs:
		try:
			doc = frappe.get_doc(doctype, name)
			doc.flags.ignore_permissions = True
			doc.cancel()
			cancelled += 1
		except Exception as e:
			frappe.log_error(f"Error cancelling {doctype} {name}: {e}")

		if cancelled % batch_size == 0:
			frappe.db.commit()
			frappe.publish_realtime(
				"bulk_delete_progress",
				{"doctype": doctype, "status": "Cancelling", "cancelled": cancelled, "total": len(submitted_docs)},
			)

	frappe.db.commit()
	frappe.publish_realtime(
		"bulk_delete_progress",
		{"doctype": doctype, "status": "Cancelled", "cancelled": cancelled},
	)


def delete_direct(doctype, delete_child_tables, filters=None):
	"""Fast path: direct DB delete, no hooks."""
	# Skip child-table cleanup when filtering: parenttype-based delete would
	# orphan/over-delete child rows whose parents weren't actually deleted.
	if delete_child_tables and not filters:
		for child_table in get_child_tables(doctype):
			frappe.db.delete(child_table, {"parenttype": doctype})

	frappe.db.delete(doctype, filters or None)
	frappe.db.commit()


def delete_with_hooks_sync(doctype, batch_size, filters=None):
	"""Synchronous delete with hooks. Used when cancel_before_delete is on
	to guarantee each doctype is fully deleted before moving to the next."""
	all_names = frappe.get_all(doctype, filters=filters or None, pluck="name")
	if not all_names:
		return

	deleted = 0
	frappe.flags.in_bulk_delete = True

	for name in all_names:
		try:
			frappe.delete_doc(doctype, name, force=True)
			deleted += 1
		except Exception as e:
			frappe.log_error(f"Error deleting {doctype} {name}: {e}")

		if deleted % batch_size == 0:
			frappe.db.commit()
			frappe.publish_realtime(
				"bulk_delete_progress",
				{"doctype": doctype, "deleted": deleted, "total": len(all_names)},
			)

	frappe.db.commit()


def delete_with_hooks(doctype, batch_size, workers, filters=None):
	"""Slow path: uses frappe.delete_doc so hooks run. Parallelized across workers."""
	all_names = frappe.get_all(doctype, filters=filters or None, pluck="name")
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

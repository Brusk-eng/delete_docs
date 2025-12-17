# Copyright (c) 2025, Rl0007 and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DeleteDocumentData(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		batch_size: DF.Int
		document: DF.Link
	# end: auto-generated types

	@frappe.whitelist()
	def bulk_delete_documents(
		self,
		doctype: str,
		batch_size: int = 100,
	):
		item_count = frappe.db.count(doctype)
		for i in range(0,item_count,batch_size):
			item_list = frappe.get_all(doctype, limit=batch_size, offset=i, pluck="name")
			frappe.enqueue("delete_docs.delete_docs.doctype.delete_document_data.delete_document_data._delete_document_batch", doctype=doctype, item_list=item_list)
			# _delete_document_batch(doctype, item_list)




def _delete_document_batch(doctype,item_list):
	for item in item_list:
		try:
			frappe.flags.in_bulk_delete = True
			frappe.delete_doc(doctype, item)
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(e, f"Error deleting document {doctype} {item}")
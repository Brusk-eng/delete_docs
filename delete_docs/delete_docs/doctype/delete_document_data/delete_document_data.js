// Copyright (c) 2025, Rl0007 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Delete Document Data", {
	refresh(frm) {
	frm.disable_save();
        		// Primary button: Delete
		frm.page.set_primary_action(__('Delete'), async ($btn) => {
			await delete_documents(frm, $btn); // true = delete
		});



	},
});

async function delete_documents(frm, $btn) {
	const values = frm.doc;


	frappe.confirm(
		__(`Are you sure you want to delete items?`),
		async () => {
			try {
				frm.call({
					method: 'bulk_delete_documents',
					args: {
						doctype: values.document,
                        batch_size: values.batch_size
					},
					doc: frm.doc,
				});

				frappe.msgprint(
					__('Deleting entries in background'),
				);
			} catch (err) {
			} finally {
				$btn
					.prop('disabled', false)
					.text("Delete");
			}
		},
	);
}

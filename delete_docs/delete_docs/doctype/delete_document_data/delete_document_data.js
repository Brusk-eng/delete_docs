// Copyright (c) 2025, Rl0007 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Delete Document Data", {
	refresh(frm) {
		frm.page.set_primary_action(__("Delete All"), async () => {
			await confirm_and_delete(frm);
		});

		frm.add_custom_button(__("Fetch Counts"), async () => {
			await frm.call("fetch_counts");
			frm.refresh_fields();
		});

		frappe.realtime.on("bulk_delete_progress", (data) => {
			frappe.show_alert({
				message: `${data.doctype}: ${data.status || "Deleting"} ${data.deleted ? "(" + data.deleted + " deleted)" : ""}`,
				indicator: data.status === "Error" ? "red" : "blue",
			});
		});

		frappe.realtime.on("bulk_delete_complete", () => {
			frappe.show_alert({
				message: __("Bulk delete completed for all DocTypes."),
				indicator: "green",
			});
		});
	},
});

async function confirm_and_delete(frm) {
	const doctype_list = (frm.doc.documents || [])
		.map((row) => row.document)
		.filter(Boolean);

	if (!doctype_list.length) {
		frappe.msgprint(__("Please add at least one DocType to delete."));
		return;
	}

	const skip_hooks = frm.doc.skip_hooks;
	const warning = skip_hooks
		? "<b>Skip Hooks is ON</b> — this will directly delete from the database with no validations or hooks."
		: "This will delete documents using frappe.delete_doc (hooks will run).";

	frappe.confirm(
		__(`Are you sure you want to delete all data for:<br><br>
			<b>${doctype_list.join(", ")}</b><br><br>
			${warning}<br><br>
			This action cannot be undone.`),
		async () => {
			await frm.call("bulk_delete_documents");
		},
	);
}

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

		(frm.doc.documents || []).forEach((row) => set_filter_field_options(frm, row));
	},
});

frappe.ui.form.on("Delete Document Item", {
	document(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "filter_field", "");
		frappe.model.set_value(cdt, cdn, "filter_value", "");
		set_filter_field_options(frm, row);
	},
});

async function set_filter_field_options(frm, row) {
	if (!row.document) return;
	await frappe.model.with_doctype(row.document);
	const meta = frappe.get_meta(row.document);
	const skip = new Set([
		"Section Break", "Column Break", "Tab Break",
		"HTML", "Button", "Heading", "Image", "Table", "Table MultiSelect",
	]);
	const fieldnames = (meta.fields || [])
		.filter((df) => df.fieldname && !skip.has(df.fieldtype))
		.map((df) => df.fieldname);
	const grid_row = frm.fields_dict.documents.grid.grid_rows_by_docname[row.name];
	if (grid_row) {
		const df = grid_row.docfields.find((d) => d.fieldname === "filter_field");
		if (df) df.options = fieldnames.join("\n");
		if (grid_row.refresh_field) grid_row.refresh_field("filter_field");
	}
}

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

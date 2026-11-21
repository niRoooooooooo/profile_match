
const registrationForm =
    document.getElementById("registrationForm");

const registrationMessage =
    document.getElementById("registrationMessage");

const registrationSubmit =
    document.getElementById("registrationSubmit");

const inventionFiles =
    document.getElementById("inventionFiles");

const registrationHeading =
    document.querySelector("#registerView h1");

const uploadMoreForm =
    document.getElementById("uploadMoreForm");

const uploadMoreMessage =
    document.getElementById("uploadMoreMessage");

const uploadMoreSubmit =
    document.getElementById("uploadMoreSubmit");

let editingInventionId = null;
let attachmentTarget = null;


// Convert comma-separated text into an array.

function splitValues(value) {
    return value
        .split(",")
        .map(item => item.trim())
        .filter(Boolean);
}


// Read the registration fields.

function collectInventionData() {
    const fields = new FormData(registrationForm);

    return {
        title: fields.get("title").trim(),
        abstract: fields.get("abstract").trim(),
        domain: fields.get("domain").trim(),

        trl: fields.get("trl")
            ? Number(fields.get("trl"))
            : null,

        ip_status: fields.get("ip_status"),

        inventors: splitValues(
            fields.get("inventors") || ""
        ),

        keywords: splitValues(
            fields.get("keywords") || ""
        ),

        confidentiality:
            fields.get("confidentiality") || "restricted"
    };
}


// Prepare the form for a new invention.

function startNewRegistration() {
    editingInventionId = null;

    registrationForm.reset();
    registrationMessage.textContent = "";

    inventionFiles.required = true;

    registrationHeading.textContent =
        "Register an invention";

    registrationSubmit.textContent =
        "Register invention & upload";
}


// Load an existing draft for editing.

function editInvention(invention) {
    if (invention.status !== "draft") {
        return;
    }

    startNewRegistration();

    editingInventionId = invention.id;

    registrationHeading.textContent =
        "Edit invention details";

    registrationSubmit.textContent =
        "Save changes";

    const fields = registrationForm.elements;

    fields.namedItem("title").value =
        invention.title || "";

    fields.namedItem("abstract").value =
        invention.abstract || "";

    fields.namedItem("domain").value =
        invention.domain || "";

    fields.namedItem("trl").value =
        invention.trl || "";

    fields.namedItem("ip_status").value =
        invention.ip_status || "Not specified";

    fields.namedItem("inventors").value =
        (invention.inventors || []).join(", ");

    fields.namedItem("keywords").value =
        (invention.keywords || []).join(", ");

    const confidentiality =
        invention.confidentiality || "restricted";

    for (const radio of
        document.querySelectorAll(
            'input[name="confidentiality"]'
        )) {
        radio.checked =
            radio.value === confidentiality;
    }

    // Existing drafts already have a record.
    // Additional files are optional when editing.

    inventionFiles.required = false;

    window.navigateTo("register");
}


// Register or edit an invention.

registrationForm.addEventListener(
    "submit",
    async function (event) {
        event.preventDefault();

        registrationSubmit.disabled = true;
        registrationMessage.textContent =
            "Saving invention...";

        let savedId = editingInventionId;

        try {
            const { client, user } =
                window.profileMatchState;

            if (!client || !user) {
                throw new Error("Please log in again.");
            }

            const files = Array.from(
                inventionFiles.files
            );

            if (!editingInventionId || files.length) {
                window.validateInventionFiles(files);
            }

            const values = collectInventionData();

            if (!values.title ||
                !values.abstract ||
                !values.domain) {
                throw new Error(
                    "Title, abstract and domain are required."
                );
            }

            if (editingInventionId) {

                // Update existing draft; do not create a duplicate.

                const { data, error } = await client
                    .from("inventions")
                    .update(values)
                    .eq("id", editingInventionId)
                    .eq("owner_id", user.id)
                    .eq("status", "draft")
                    .select("id")
                    .single();

                if (error) throw error;

                savedId = data.id;

            } else {

                // Create a new draft invention.

                const { data, error } = await client
                    .from("inventions")
                    .insert({
                        ...values,
                        owner_id: user.id,
                        status: "draft"
                    })
                    .select("id")
                    .single();

                if (error) throw error;

                savedId = data.id;
            }

            let results = {
                uploaded: [],
                failed: []
            };

            if (files.length) {
                results =
                    await window.uploadInventionFiles({
                        client,
                        userId: user.id,
                        inventionId: savedId,
                        files,
                        onProgress: message => {
                            registrationMessage.textContent =
                                message;
                        }
                    });
            }

            startNewRegistration();

            window.navigateTo("dashboard");

            await window.refreshInventions();

            if (results.failed.length) {
                const names = results.failed
                    .map(item => item.filename)
                    .join(", ");

                window.showDashboardNotice(
                    `Invention saved as draft. ` +
                    `${results.uploaded.length} document(s) uploaded. ` +
                    `Failed: ${names}. ` +
                    `Use Add documents to retry failed files.`,
                    "warning"
                );
            } else {
                window.showDashboardNotice(
                    "Invention saved successfully. " +
                    "Documents are stored privately in Supabase.",
                    "success"
                );
            }

        } catch (error) {
            console.error("Registration failed:", error);

            registrationMessage.textContent = savedId
                ? "Draft was saved, but the process " +
                  "did not finish: " + error.message
                : "Could not register invention: " +
                  error.message;

        } finally {
            registrationSubmit.disabled = false;
        }
    }
);


// Open the additional-document upload screen.

function showAttachDocuments(invention) {
    attachmentTarget = invention;

    uploadMoreForm.reset();
    uploadMoreMessage.textContent = "";

    document.getElementById("attachTitle")
        .textContent = invention.title;

    window.navigateTo("attach");
}


// Upload documents to an existing invention.

uploadMoreForm.addEventListener(
    "submit",
    async function (event) {
        event.preventDefault();

        uploadMoreSubmit.disabled = true;
        uploadMoreMessage.textContent =
            "Preparing documents...";

        try {
            if (!attachmentTarget) {
                throw new Error("No invention selected.");
            }

            const { client, user } =
                window.profileMatchState;

            if (!client || !user) {
                throw new Error("Please log in again.");
            }

            const files = Array.from(
                document.getElementById(
                    "additionalFiles"
                ).files
            );

            const results =
                await window.uploadInventionFiles({
                    client,
                    userId: user.id,
                    inventionId: attachmentTarget.id,
                    files,
                    onProgress: message => {
                        uploadMoreMessage.textContent =
                            message;
                    }
                });

            uploadMoreForm.reset();

            if (results.failed.length) {
                uploadMoreMessage.textContent =
                    `${results.uploaded.length} uploaded, ` +
                    `${results.failed.length} failed: ` +
                    results.failed
                        .map(item =>
                            `${item.filename} (${item.reason})`
                        )
                        .join("; ");
            } else {
                uploadMoreMessage.textContent =
                    `${results.uploaded.length} ` +
                    "document(s) uploaded successfully.";
            }

            await window.refreshInventions();

        } catch (error) {
            console.error("Document upload failed:", error);

            uploadMoreMessage.textContent =
                "Upload failed: " + error.message;

        } finally {
            uploadMoreSubmit.disabled = false;
        }
    }
);


// Expose actions to dashboard.js.

window.profileMatchRegistration = {
    startNew: startNewRegistration,
    edit: editInvention,
    showAttach: showAttachDocuments
};

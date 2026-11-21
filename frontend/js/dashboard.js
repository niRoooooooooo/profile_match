
/*
===============================================
PROFILE MATCH — INNOVATOR DASHBOARD
Phase 3: Invention Management
===============================================
*/

// ========================================
// 1. DOM ELEMENTS
// ========================================

const welcomeTitle =
    document.getElementById("welcomeTitle");

const accountName =
    document.getElementById("accountName");

const inventionList =
    document.getElementById("inventionList");

const dashboardError =
    document.getElementById("dashboardError");

const dashboardNotice =
    document.getElementById("dashboardNotice");

const logoutButton =
    document.getElementById("logoutButton");


// ========================================
// 2. SUPABASE CONFIGURATION
// ========================================

// Actual Storage bucket ID.
const STORAGE_BUCKET = "invention-document";

// Shared authenticated state.
window.profileMatchState = {
    client: null,
    user: null
};


// ========================================
// 3. PAGE NAVIGATION
// ========================================

window.navigateTo = function (view) {

    const sections = {
        dashboard: "dashboardView",
        register: "registerView",
        attach: "attachView"
    };

    if (!sections[view]) {
        console.error("Unknown view:", view);
        return;
    }

    for (const [name, id] of Object.entries(sections)) {

        const section = document.getElementById(id);

        if (section) {
            section.hidden = name !== view;
        }
    }

    document.querySelectorAll(
        ".side-nav [data-view]"
    ).forEach(button => {

        button.classList.toggle(
            "nav-active",
            button.dataset.view === view
        );
    });

    window.scrollTo(0, 0);
};


// ========================================
// 4. NAVIGATION BUTTONS
// ========================================

document.querySelectorAll("[data-view]")
    .forEach(button => {

        button.addEventListener("click", () => {

            const view = button.dataset.view;

            if (view === "register") {
                window.profileMatchRegistration.startNew();
            }

            window.navigateTo(view);
        });
    });


// ========================================
// 5. DASHBOARD NOTIFICATIONS
// ========================================

window.showDashboardNotice = function (
    message,
    type = "success"
) {

    if (!dashboardNotice) return;

    dashboardNotice.textContent = message;

    dashboardNotice.className =
        `notice notice-${type}`;

    dashboardNotice.hidden = false;
};


// ========================================
// 6. BUTTON HELPER
// ========================================

function makeButton(label, callback) {

    const button = document.createElement("button");

    button.type = "button";
    button.className = "btn small-button";
    button.textContent = label;

    button.addEventListener("click", callback);

    return button;
}


// ========================================
// 7. OPEN PRIVATE DOCUMENT
// ========================================

async function openPrivateDocument(documentRecord) {

    const client = window.profileMatchState.client;

    if (!client) {
        dashboardError.textContent =
            "Please log in again.";
        return;
    }

    dashboardError.textContent = "";

    const tab = window.open(
        "about:blank",
        "_blank"
    );

    if (tab) {
        tab.opener = null;
    }

    try {

        const { data, error } =
            await client.storage
                .from(STORAGE_BUCKET)
                .createSignedUrl(
                    documentRecord.storage_path,
                    60
                );

        if (error) {
            throw error;
        }

        if (!data || !data.signedUrl) {
            throw new Error(
                "Supabase did not return a document URL."
            );
        }

        if (tab) {
            tab.location.replace(data.signedUrl);
        } else {
            window.location.assign(data.signedUrl);
        }

    } catch (error) {

        if (tab) {
            tab.close();
        }

        console.error(
            "Document access error:",
            error
        );

        dashboardError.textContent =
            "Could not open document: " +
            error.message;
    }
}


// ========================================
// 8. DELETE INVENTION
// ========================================

async function deleteInvention(invention, deleteButton) {

    // Ask before permanently deleting anything.
    const confirmed = window.confirm(
        `Are you sure you want to delete "${invention.title}"?\n\n` +
        "This will permanently delete:\n" +
        "- The registered invention\n" +
        "- All uploaded documents\n" +
        "- The associated AI invention profile\n\n" +
        "This action cannot be undone."
    );

    if (!confirmed) {
        return;
    }

    const { client, user } =
        window.profileMatchState;

    if (!client || !user) {

        dashboardError.textContent =
            "Authentication required. Please log in again.";

        return;
    }

    deleteButton.disabled = true;
    deleteButton.textContent = "Deleting...";

    dashboardError.textContent = "";

    let filesRemoved = false;
    let databaseDeleted = false;

    try {

        // --------------------------------
        // STEP 1: GET DOCUMENT METADATA
        // --------------------------------

        const {
            data: documents,
            error: docsError
        } =
            await client
                .from("invention_documents")
                .select("storage_path")
                .eq("invention_id", invention.id);

        if (docsError) {
            throw new Error(
                "Could not retrieve documents: " +
                docsError.message
            );
        }

        // Get storage paths.
        const filePaths = (documents || [])
            .map(doc => doc.storage_path)
            .filter(Boolean);


        // --------------------------------
        // STEP 2: DELETE STORAGE FILES
        // --------------------------------

        if (filePaths.length > 0) {

            // Process documents in batches.
            for (let i = 0; i < filePaths.length; i += 100) {

                const batch = filePaths.slice(
                    i,
                    i + 100
                );

                const { error: storageError } =
                    await client.storage
                        .from(STORAGE_BUCKET)
                        .remove(batch);

                if (storageError) {
                    throw new Error(
                        "Storage deletion failed: " +
                        storageError.message
                    );
                }

                filesRemoved = true;
            }

            console.log(
                "Deleted files from Supabase Storage:",
                filePaths.length
            );
        }


        // --------------------------------
        // STEP 3: DELETE INVENTION RECORD
        // --------------------------------

        const {
            data: deleted,
            error: deleteError
        } =
            await client
                .from("inventions")
                .delete()
                .eq("id", invention.id)
                .eq("owner_id", user.id)
                .select("id");

        if (deleteError) {
            throw new Error(
                "Database deletion failed: " +
                deleteError.message
            );
        }

        if (!deleted || deleted.length === 0) {
            throw new Error(
                "Invention was not deleted. " +
                "Check your Supabase permissions."
            );
        }

        databaseDeleted = true;

        // The invention_documents and invention_profiles
        // records are removed automatically if their
        // foreign keys use ON DELETE CASCADE.

        console.log(
            "Invention deleted successfully:",
            invention.id
        );


        // --------------------------------
        // STEP 4: SHOW SUCCESS MESSAGE
        // --------------------------------

        window.showDashboardNotice(
            `"${invention.title}" deleted successfully.`,
            "success"
        );


        // --------------------------------
        // STEP 5: REFRESH DASHBOARD
        // --------------------------------

        try {
            await window.refreshInventions();
        } catch (refreshError) {

            console.error(
                "Dashboard refresh failed:",
                refreshError
            );

            dashboardError.textContent =
                "The invention was deleted, but the " +
                "dashboard could not refresh. " +
                "Please reload the page.";
        }

    } catch (error) {

        console.error(
            "Delete invention failed:",
            error
        );

        let message =
            "Deletion failed: " + error.message;

        if (filesRemoved && !databaseDeleted) {

            message +=
                " Some files may have been removed " +
                "before the database operation failed. " +
                "Check the invention before retrying.";
        }

        dashboardError.textContent = message;

    } finally {

        if (!databaseDeleted) {
            deleteButton.disabled = false;
            deleteButton.textContent = "Delete invention";
        }
    }
}


// ========================================
// 9. LOAD INVENTIONS
// ========================================

window.refreshInventions = async function () {

    const { client, user } =
        window.profileMatchState;

    if (!client || !user) {
        throw new Error(
            "Authentication is required."
        );
    }

    dashboardError.textContent = "";

    // Fetch current user's inventions.
    const { data: inventions, error } =
        await client
            .from("inventions")
            .select(
                "id,title,abstract,domain,trl," +
                "ip_status,inventors,keywords," +
                "confidentiality,status,created_at"
            )
            .eq("owner_id", user.id)
            .order("created_at", {
                ascending: false
            });

    if (error) {
        throw error;
    }

    inventionList.replaceChildren();


    // ========================================
    // 10. EMPTY DASHBOARD
    // ========================================

    if (!inventions || inventions.length === 0) {

        const empty =
            document.createElement("div");

        empty.className = "empty-state";

        const heading =
            document.createElement("h3");

        heading.textContent =
            "No inventions registered";

        const description =
            document.createElement("p");

        description.className = "muted";

        description.textContent =
            "Register your first invention to get started.";

        const button = makeButton(
            "+ Register invention",
            () => {

                window.profileMatchRegistration
                    .startNew();

                window.navigateTo("register");
            }
        );

        button.classList.add("primary");

        empty.append(
            heading,
            description,
            button
        );

        inventionList.appendChild(empty);

        return;
    }


    // ========================================
    // 11. FETCH DOCUMENT METADATA
    // ========================================

    const inventionIds =
        inventions.map(item => item.id);

    const {
        data: documents,
        error: docsError
    } =
        await client
            .from("invention_documents")
            .select(
                "id,invention_id," +
                "original_filename,storage_path,uploaded_at"
            )
            .in("invention_id", inventionIds)
            .order("uploaded_at", {
                ascending: false
            });

    if (docsError) {
        throw docsError;
    }

    // Group documents by invention.
    const docsByInvention = new Map();

    for (const documentRecord of documents || []) {

        if (!docsByInvention.has(
            documentRecord.invention_id
        )) {

            docsByInvention.set(
                documentRecord.invention_id,
                []
            );
        }

        docsByInvention
            .get(documentRecord.invention_id)
            .push(documentRecord);
    }


    // ========================================
    // 12. DISPLAY INVENTION CARDS
    // ========================================

    for (const invention of inventions) {

        const card =
            document.createElement("article");

        card.className = "invention-card";


        // Invention title.
        const heading =
            document.createElement("h3");

        heading.textContent =
            invention.title;


        // Domain and TRL.
        const details =
            document.createElement("p");

        details.className = "muted";

        details.textContent =
            `${invention.domain || "No domain"} | ` +
            `TRL: ${invention.trl ?? "Not specified"}`;


        // Registration status.
        const status =
            document.createElement("span");

        status.className = "status-badge";

        status.textContent =
            invention.status || "draft";


        // Confidentiality level.
        const privacy =
            document.createElement("p");

        privacy.className = "muted small-text";

        privacy.textContent =
            "Confidentiality: " +
            (invention.confidentiality ||
                "restricted");


        // Associated documents.
        const files =
            docsByInvention.get(invention.id) || [];


        // Document count.
        const fileHeading =
            document.createElement("p");

        fileHeading.className = "small-text";

        fileHeading.textContent =
            `Documents: ${files.length}`;


        // Document buttons.
        const fileList =
            document.createElement("div");

        fileList.className = "document-list";

        for (const doc of files) {

            const fileButton = makeButton(
                doc.original_filename,
                () => openPrivateDocument(doc)
            );

            fileButton.title =
                "Open private document";

            fileList.appendChild(fileButton);
        }


        // ========================================
        // 13. INVENTION ACTIONS
        // ========================================

        const actions =
            document.createElement("div");

        actions.className = "form-actions";


        // --------------------------------
        // ADD DOCUMENTS BUTTON
        // --------------------------------

        const addDocumentButton = makeButton(
            "Add documents",
            () => {

                window.profileMatchRegistration
                    .showAttach(invention);
            }
        );

        actions.appendChild(addDocumentButton);


        // --------------------------------
        // EDIT DRAFT BUTTON
        // --------------------------------

        if (invention.status === "draft") {

            const editButton = makeButton(
                "Edit draft",
                () => {

                    window.profileMatchRegistration
                        .edit(invention);
                }
            );

            actions.appendChild(editButton);
        }


        // --------------------------------
        // DELETE INVENTION BUTTON
        // --------------------------------

        const deleteButton = makeButton(
            "Delete invention",
            () => {

                deleteInvention(
                    invention,
                    deleteButton
                );
            }
        );

        deleteButton.classList.add("btn-danger");

        actions.appendChild(deleteButton);


        // ========================================
        // 14. ADD CARD TO DASHBOARD
        // ========================================

        card.append(
            heading,
            details,
            status,
            privacy,
            fileHeading,
            fileList,
            actions
        );

        inventionList.appendChild(card);
    }
};


// ========================================
// 15. INITIALIZE AUTHENTICATED DASHBOARD
// ========================================

async function loadDashboard() {

    try {

        const client =
            await window.getSupabase();

        // Verify the authenticated user.
        const { data, error: authError } =
            await client.auth.getUser();

        if (authError || !data.user) {

            window.location.replace("/login");
            return;
        }

        const user = data.user;


        // ========================================
        // 16. FETCH INNOVATOR PROFILE
        // ========================================

        const {
            data: profile,
            error: profileError
        } =
            await client
                .from("user_profiles")
                .select("full_name,role")
                .eq("id", user.id)
                .single();

        if (profileError) {
            throw profileError;
        }

        if (!profile) {
            throw new Error(
                "Innovator profile not found."
            );
        }

        if (profile.role !== "innovator") {
            throw new Error(
                "Innovator access required."
            );
        }


        // Save authenticated state.
        window.profileMatchState.client = client;
        window.profileMatchState.user = user;


        // ========================================
        // 17. UPDATE DASHBOARD HEADER
        // ========================================

        welcomeTitle.textContent =
            `Welcome, ${profile.full_name}`;

        accountName.textContent =
            profile.full_name;


        // Load inventions and documents.
        await window.refreshInventions();

    } catch (error) {

        console.error(
            "Dashboard initialization error:",
            error
        );

        inventionList.replaceChildren();

        dashboardError.textContent =
            "Failed to load dashboard: " +
            error.message;
    }
}


// ========================================
// 18. GOOGLE / SUPABASE SIGN OUT
// ========================================

logoutButton.addEventListener(
    "click",
    async () => {

        logoutButton.disabled = true;

        logoutButton.textContent =
            "Signing out...";

        dashboardError.textContent = "";

        try {

            const client =
                await window.getSupabase();

            // End the local Supabase session.
            const { error } =
                await client.auth.signOut({
                    scope: "local"
                });

            if (error) {
                throw error;
            }

            // Clear application state.
            window.profileMatchState.client = null;
            window.profileMatchState.user = null;

            // Redirect to Google login.
            window.location.replace("/login");

        } catch (error) {

            console.error(
                "Sign out failed:",
                error
            );

            dashboardError.textContent =
                "Sign out failed: " +
                error.message;

            logoutButton.disabled = false;

            logoutButton.textContent =
                "Sign out";
        }
    }
);


// ========================================
// 19. START APPLICATION
// ========================================

loadDashboard();

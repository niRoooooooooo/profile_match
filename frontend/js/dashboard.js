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

// The whole Innovator workspace (navigation, inventions,
// registration, uploads). Hidden in index.html itself (so it
// never paints before authorization) and revealed only after
// the server confirms that this account may use it.
const appRoot =
    document.querySelector("body > .app");

if (appRoot) {
    appRoot.hidden = true;
}

// "Checking account access..." line shown until a decision.
function clearAccountCheckStatus() {
    const pending = document.getElementById("accountCheckStatus");

    if (pending) {
        pending.remove();
    }
}


// ========================================
// 1b. APPLICATION-WIDE ACCOUNT ACCESS
// ========================================
//
// GET /api/access/me (the existing unified authorization
// endpoint) decides whether the dashboard may be used:
//   200 for this user, account active -> dashboard
//   401 -> existing sign-in behaviour (/login)
//   403 -> "Account Restricted" (no business controls)
//   anything else / network error -> "could not be checked"
//         (never presented as a restriction)
// An empty invention list is NEVER taken as a sign of a
// restriction or of an active account.

const ACCESS_URL = "/api/access/me";

let accessGeneration = 0;
let accountLocked = false;
let accessConfirmed = false;

function showAccessGate(title, text, withRetry) {

    accountLocked = true;
    document.body.dataset.accountLocked = "true";
    clearAccountCheckStatus();

    // Remove the workspace entirely: no records, registration,
    // uploads, editing, deletion, generation or submission.
    if (appRoot) {
        appRoot.remove();
    }

    const switcher = document.getElementById("roleSwitcher");

    if (switcher) {
        switcher.hidden = true;
        switcher.replaceChildren();
    }

    let gate = document.getElementById("accountGate");

    if (!gate) {
        gate = document.createElement("main");
        gate.id = "accountGate";
        gate.className = "content";
        gate.tabIndex = -1;
        document.body.append(gate);
    }

    const heading = document.createElement("h1");
    heading.textContent = title;

    const message = document.createElement("p");
    message.setAttribute("role", "alert");
    message.textContent = text;

    gate.replaceChildren(heading, message);

    if (withRetry) {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn";
        retry.textContent = "Try again";
        retry.addEventListener("click", () => window.location.reload());
        gate.append(retry);
    }

    // The header's existing Sign out button stays the only
    // account control (existing secure sign-out flow).
    gate.focus();
}

function showRestricted() {
    showAccessGate(
        "Account Restricted",
        "Your account is currently restricted. Please contact the " +
        "Administrator if you believe this is a mistake.",
        false
    );
}

function showAccessUnavailable() {
    showAccessGate(
        "Account access could not be checked",
        "The authorization service is temporarily unavailable, so the " +
        "dashboard is not shown. This does not mean your account is " +
        "restricted. Please try again later.",
        true
    );
}

// Resolves to "active", "restricted", "unavailable",
// "signed_out" or "stale" (a newer check or another account).
async function checkAccountAccess(client, expectedUserId) {

    const mine = ++accessGeneration;

    let token = null;

    try {
        const { data } = await client.auth.getSession();
        const session = data && data.session;

        if (session && session.user && session.user.id === expectedUserId) {
            token = session.access_token;
        }
    } catch (error) {
        token = null;
    }

    if (!token) {
        return "signed_out";
    }

    let outcome = "unavailable";

    try {
        const response = await fetch(ACCESS_URL, {
            credentials: "same-origin",
            cache: "no-store",
            headers: {
                Accept: "application/json",
                Authorization: "Bearer " + token
            }
        });

        if (response.status === 401) {
            outcome = "signed_out";
        } else if (response.status === 403) {
            outcome = "restricted";
        } else if (response.ok) {
            const body = await response.json();
            outcome = body
                && body.user_id === expectedUserId
                && body.account_status === "active"
                && body.innovator === true
                ? "active"
                : "unavailable";
        }
    } catch (error) {
        outcome = "unavailable";
    }

    // Ignore a response that a newer check replaced, or that
    // belongs to an account no longer signed in here.
    if (mine !== accessGeneration) {
        return "stale";
    }

    try {
        const { data } = await client.auth.getSession();
        const current = data && data.session && data.session.user;

        if (!current || current.id !== expectedUserId) {
            return "stale";
        }
    } catch (error) {
        return "stale";
    }

    return outcome;
}

// Applies a non-active outcome. Returns true if the page may
// keep showing the dashboard.
function applyAccessOutcome(outcome) {

    if (outcome === "active") {
        return true;
    }

    if (outcome === "signed_out") {
        window.location.replace("/login");
    } else if (outcome === "restricted") {
        showRestricted();
    } else if (outcome === "unavailable") {
        showAccessUnavailable();
    } else if (appRoot && appRoot.isConnected) {
        // "stale": the account changed; never show its data.
        appRoot.hidden = true;
        window.location.reload();
    }

    return false;
}

// Re-check on tab return, history restoration and account
// changes. A locked page is never unlocked without a reload.
function watchAccountAccess(client, userId) {

    const recheck = async () => {
        if (accountLocked) {
            return;
        }
        applyAccessOutcome(await checkAccountAccess(client, userId));
    };

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            recheck();
        }
    });

    window.addEventListener("pageshow", event => {
        if (event.persisted) {
            recheck();
        }
    });

    if (client.auth && typeof client.auth.onAuthStateChange === "function") {
        client.auth.onAuthStateChange((event, session) => {
            const current = session && session.user ? session.user.id : null;

            // This tab's own sign-out redirects by itself.
            if (current !== userId && !signingOut) {
                // Signed out or another account: hide this account's
                // data at once, then start over for the new state.
                accessGeneration += 1;

                if (appRoot) {
                    appRoot.hidden = true;
                }

                setTimeout(() => window.location.reload(), 0);
            }
        });
    }
}


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
// PHASE 4: OPEN THIS INVENTION'S AI REPORT
// ========================================

function openInventionReport(invention) {
    // The report page checks the user's Google session
    // and loads only the requested, owned invention.
    const inventionId = encodeURIComponent(invention.id);
    window.location.assign(
        `/assets/invention_report.html?invention_id=${inventionId}`
    );
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

    // ----------------------------------------
    // PHASE 4: READ OWN SAVED AI REPORT DRAFTS
    // ----------------------------------------
    // This is read-only and respects Supabase RLS.
    // The browser cannot directly modify agent output.
    const {
        data: aiDraftRows,
        error: aiDraftError
    } = await client
        .from("invention_profile_drafts")
        .select("invention_id,edited_data,generation_number")
        .in("invention_id", inventionIds);

    if (aiDraftError) {
        throw new Error(
            "Could not load invention AI report status: " +
            aiDraftError.message
        );
    }

    const aiDraftByInvention = new Map(
        (aiDraftRows || []).map(item => [
            item.invention_id,
            item
        ])
    );

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
        // PHASE 4: AI REPORT FOR THIS INVENTION
        // ========================================

        const aiDraft = aiDraftByInvention.get(invention.id);
        const aiReportSection = document.createElement("section");
        aiReportSection.className = "box";
        aiReportSection.style.marginTop = "14px";
        aiReportSection.style.padding = "14px";
        aiReportSection.style.border = "1px solid #dce3eb";
        aiReportSection.style.borderRadius = "8px";

        const aiHeading = document.createElement("h4");
        aiHeading.textContent = "AI-generated invention report";
        aiHeading.style.margin = "0 0 8px";
        aiReportSection.appendChild(aiHeading);

        const aiInfo = document.createElement("p");
        aiInfo.className = "muted small-text";

        if (aiDraft) {
            const summary = aiDraft.edited_data
                ?.identity?.concise_summary?.value;
            aiInfo.textContent = summary
                ? summary.slice(0, 260) +
                    (summary.length > 260 ? "…" : "")
                : "Draft saved. Open the report to review and edit it.";
        } else {
            aiInfo.textContent =
                "No AI report yet. Generate one from this " +
                "invention's supporting documents.";
        }

        aiReportSection.appendChild(aiInfo);

        const aiStatus = document.createElement("p");
        aiStatus.className = "muted small-text";
        aiStatus.textContent = aiDraft
            ? `Saved AI draft · Generation ${aiDraft.generation_number}`
            : "Not generated";
        aiReportSection.appendChild(aiStatus);

        const openReportButton = makeButton(
            aiDraft ? "View / Edit / Submit AI report" : "Generate AI report",
            () => openInventionReport(invention)
        );
        if (!aiDraft) {
            openReportButton.classList.add("primary");
        }
        aiReportSection.appendChild(openReportButton);

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
            aiReportSection,
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

        // Confirm application-wide account access BEFORE any
        // dashboard data is loaded or any control is shown.
        const access =
            await checkAccountAccess(client, user.id);

        if (!applyAccessOutcome(access)) {
            return;
        }

        accessConfirmed = true;
        clearAccountCheckStatus();

        if (appRoot) {
            appRoot.hidden = false;
        }

        watchAccountAccess(client, user.id);


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

        // Failed before access was confirmed: the workspace is
        // still hidden, so say that access could not be checked.
        if (!accessConfirmed) {
            showAccessUnavailable();
            return;
        }

        inventionList.replaceChildren();

        dashboardError.textContent =
            "Failed to load dashboard: " +
            error.message;
    }
}


// ========================================
// 18. GOOGLE / SUPABASE SIGN OUT
// ========================================

// End the server-side interface sessions (Administrator and
// institutional UI sessions) through the shared helper of the
// interface switcher script. Bounded wait; never throws.
async function endInterfaceSessions() {

    const helper = window.ProfileMatchUISessions;

    if (!helper || typeof helper.end !== "function") {
        return { confirmed: false };
    }

    try {
        return await helper.end();
    } catch (error) {
        return { confirmed: false };
    }
}

let signingOut = false;

logoutButton.addEventListener(
    "click",
    async () => {

        // Prevent duplicate sign-out actions.
        if (signingOut) {
            return;
        }

        signingOut = true;

        logoutButton.disabled = true;

        logoutButton.textContent =
            "Signing out...";

        dashboardError.textContent = "";

        // End the server UI sessions first and wait for the
        // server to confirm (time-limited).
        const ended = await endInterfaceSessions();

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

            if (!ended.confirmed) {
                // Signed out locally; the server did not confirm
                // that the interface sessions ended. They expire
                // on their own (15 minutes at most).
                const text =
                    "Signed out on this device. The server could not " +
                    "confirm that interface sessions ended; they " +
                    "expire within 15 minutes.";
                const gate = document.getElementById("accountGate");

                if (dashboardError.isConnected || !gate) {
                    dashboardError.textContent = text;
                } else {
                    const note = document.createElement("p");
                    note.setAttribute("role", "status");
                    note.textContent = text;
                    gate.append(note);
                }

                console.warn(
                    "Interface sessions were not confirmed as ended."
                );

                await new Promise(
                    resolve => setTimeout(resolve, 2500)
                );
            }

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

            signingOut = false;

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

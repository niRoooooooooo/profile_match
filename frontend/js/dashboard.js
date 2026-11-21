
const welcomeTitle = document.getElementById("welcomeTitle");
const accountName = document.getElementById("accountName");
const inventionList = document.getElementById("inventionList");
const dashboardError = document.getElementById("dashboardError");
const logoutButton = document.getElementById("logoutButton");


// ================================
// LOAD INNOVATOR DASHBOARD
// ================================

async function loadDashboard() {
    try {
        const client = await window.getSupabase();

        // Check authenticated user
        const { data, error: authError } =
            await client.auth.getUser();

        if (authError || !data.user) {
            window.location.replace("/login");
            return;
        }

        const user = data.user;

        // Fetch user profile
        const { data: profile, error: profileError } =
            await client
                .from("user_profiles")
                .select("full_name,role")
                .eq("id", user.id)
                .single();

        if (profileError) {
            throw profileError;
        }

        if (profile.role !== "innovator") {
            throw new Error("Innovator access required");
        }

        // Display innovator name
        welcomeTitle.textContent =
            `Welcome, ${profile.full_name}`;

        accountName.textContent = profile.full_name;

        // Fetch only this innovator's inventions
        const { data: inventions, error: inventionsError } =
            await client
                .from("inventions")
                .select("id,title,domain,trl,status,created_at")
                .eq("owner_id", user.id)
                .order("created_at", { ascending: false });

        if (inventionsError) {
            throw inventionsError;
        }

        inventionList.replaceChildren();

        // Display empty state
        if (!inventions || inventions.length === 0) {
            const message = document.createElement("p");
            message.className = "muted";
            message.textContent =
                "You haven't registered any inventions yet.";

            inventionList.appendChild(message);
            return;
        }

        // Display registered inventions
        inventions.forEach(invention => {
            const item = document.createElement("div");
            item.className = "invention-item";

            const title = document.createElement("strong");
            title.textContent = invention.title;

            const status = document.createElement("p");
            status.className = "muted";
            status.textContent =
                `Status: ${invention.status}`;

            const domain = document.createElement("p");
            domain.className = "muted";
            domain.textContent =
                `Domain: ${invention.domain || "Not specified"}`;

            item.append(title, status, domain);
            inventionList.appendChild(item);
        });

    } catch (error) {
        console.error("Dashboard loading error:", error);

        inventionList.replaceChildren();

        dashboardError.textContent =
            "Failed to load dashboard: " + error.message;
    }
}


// ================================
// SIGN OUT
// ================================

logoutButton.addEventListener("click", async () => {

    // Prevent repeated clicks
    logoutButton.disabled = true;
    logoutButton.textContent = "Signing out...";

    dashboardError.textContent = "";

    try {
        const client = await window.getSupabase();

        // Sign out from the current local session
        const { error } = await client.auth.signOut({
            scope: "local"
        });

        if (error) {
            throw error;
        }

        // Redirect to login page
        window.location.replace("/login");

    } catch (error) {
        console.error("Logout failed:", error);

        dashboardError.textContent =
            "Sign out failed: " + error.message;

        // Restore button if logout fails
        logoutButton.disabled = false;
        logoutButton.textContent = "Sign out";
    }
});


// ================================
// INITIALIZE DASHBOARD
// ================================

loadDashboard();

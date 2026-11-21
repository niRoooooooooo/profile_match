
const welcomeTitle = document.getElementById("welcomeTitle");
const accountName = document.getElementById("accountName");
const inventionList = document.getElementById("inventionList");
const dashboardError = document.getElementById("dashboardError");
const logoutButton = document.getElementById("logoutButton");

async function loadDashboard() {
    try {
        const client = await window.getSupabase();

        const { data, error: authError } =
            await client.auth.getUser();

        if (authError || !data.user) {
            window.location.replace("/login");
            return;
        }

        const user = data.user;

        const { data: profile, error: profileError } =
            await client
                .from("user_profiles")
                .select("full_name,role")
                .eq("id", user.id)
                .single();

        if (profileError) throw profileError;

        if (profile.role !== "innovator") {
            throw new Error("Innovator access required");
        }

        welcomeTitle.textContent =
            `Welcome, ${profile.full_name}`;

        accountName.textContent = profile.full_name;

        const { data: inventions, error: inventionsError } =
            await client
                .from("inventions")
                .select("id,title,domain,trl,status,created_at")
                .eq("owner_id", user.id)
                .order("created_at", { ascending: false });

        if (inventionsError) throw inventionsError;

        inventionList.replaceChildren();

        if (inventions.length === 0) {
            const message = document.createElement("p");
            message.className = "muted";
            message.textContent =
                "You haven't registered any inventions yet.";

            inventionList.appendChild(message);
            return;
        }

        inventions.forEach(invention => {
            const item = document.createElement("div");
            item.className = "invention-item";

            const title = document.createElement("strong");
            title.textContent = invention.title;

            const status = document.createElement("p");
            status.className = "muted";
            status.textContent = invention.status;

            item.append(title, status);
            inventionList.appendChild(item);
        });

    } catch (err) {
        inventionList.replaceChildren();
        dashboardError.textContent = err.message;
    }
}

logoutButton.addEventListener("click", async () => {
    const client = await window.getSupabase();

    const { error } = await client.auth.signOut();

    if (error) {
        dashboardError.textContent = error.message;
        return;
    }

    window.location.replace("/login");
});

loadDashboard();

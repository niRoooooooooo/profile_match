
const loginButton = document.getElementById("googleLogin");
const loginError = document.getElementById("loginError");

loginButton.addEventListener("click", async () => {
    loginError.textContent = "";
    loginButton.disabled = true;

    try {
        const client = await window.getSupabase();

        const { error } = await client.auth.signInWithOAuth({
            provider: "google",
            options: {
                redirectTo: "http://localhost:8000/dashboard"
            }
        });

        if (error) {
            throw error;
        }

    } catch (err) {
        loginError.textContent = err.message;
        loginButton.disabled = false;
    }
});

async function checkLogin() {
    try {
        const client = await window.getSupabase();
        const { data } = await client.auth.getUser();

        if (data.user) {
            window.location.replace("/dashboard");
        }
    } catch (err) {
        console.error("Session check:", err.message);
    }
}

checkLogin();

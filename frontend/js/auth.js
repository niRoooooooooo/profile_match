
const loginButton = document.getElementById("googleLogin");
const loginError = document.getElementById("loginError");


// ==================================
// GOOGLE LOGIN
// ==================================

loginButton.addEventListener("click", async () => {

    loginError.textContent = "";
    loginButton.disabled = true;
    loginButton.textContent = "Connecting to Google...";

    try {
        const client = await window.getSupabase();

        const { error } = await client.auth.signInWithOAuth({
            provider: "google",

            options: {
                redirectTo:
                    window.location.origin + "/dashboard",

                // Always show Google account selection
                queryParams: {
                    prompt: "select_account"
                }
            }
        });

        if (error) {
            throw error;
        }

    } catch (error) {
        console.error("Google login failed:", error);

        loginError.textContent = error.message;

        loginButton.disabled = false;
        loginButton.textContent = "Continue with Google";
    }
});


// ==================================
// CHECK EXISTING SESSION
// ==================================

async function checkLogin() {

    try {
        const client = await window.getSupabase();

        const { data, error } = await client.auth.getUser();

        if (!error && data.user) {
            window.location.replace("/dashboard");
        }

    } catch (error) {
        console.error("Session check failed:", error);
    }
}


// Check session when login page loads
checkLogin();

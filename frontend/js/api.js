
let clientPromise = null;

window.getSupabase = function () {
    if (!clientPromise) {
        clientPromise = (async () => {
            const response = await fetch("/api/config/public");

            if (!response.ok) {
                throw new Error("Supabase configuration unavailable");
            }

            const config = await response.json();

            if (!window.supabase) {
                throw new Error("Supabase JavaScript library not loaded");
            }

            return window.supabase.createClient(
                config.url,
                config.publishableKey
            );
        })();
    }

    return clientPromise;
};

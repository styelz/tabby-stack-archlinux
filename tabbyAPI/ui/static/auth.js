(function () {
  const form = document.getElementById("login-form");
  if (!form) return;
  const error = document.getElementById("login-error");
  const button = document.getElementById("login-btn");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    button.disabled = true;
    try {
      const response = await fetch("/ui/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          username: document.getElementById("username").value,
          password: document.getElementById("password").value,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "Invalid username or password.");
      }
      window.location.href = data.redirect || "/ui";
    } catch (err) {
      error.hidden = false;
      error.textContent = err.message || "Sign-in failed.";
    } finally {
      button.disabled = false;
    }
  });
})();

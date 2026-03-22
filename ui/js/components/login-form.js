/**
 * Login form — rendered when session is not authenticated.
 */
function renderLoginForm(container) {
    // Hide sidebar on login page
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.style.display = 'none';
    container.style.marginLeft = '0';

    container.innerHTML = `
        <div style="max-width:360px;margin:120px auto;text-align:center">
            <h1 style="color:var(--accent);margin-bottom:24px">Octopus Registry</h1>
            <form id="login-form">
                <input type="password" id="login-password" class="search-bar"
                    placeholder="UI password" autofocus
                    style="text-align:center;margin-bottom:12px" />
                <button type="submit" class="btn btn-primary" style="width:100%">Sign in</button>
                <div id="login-error" style="color:var(--danger);margin-top:12px;font-size:13px;display:none"></div>
            </form>
        </div>
    `;

    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const password = document.getElementById('login-password').value;
        try {
            const resp = await fetch('/ui/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `password=${encodeURIComponent(password)}`,
                credentials: 'same-origin',
                redirect: 'manual',
            });
            if (resp.ok || resp.type === 'opaqueredirect' || resp.status === 302) {
                // Restore sidebar
                if (sidebar) sidebar.style.display = '';
                container.style.marginLeft = '';
                Router.navigate('/ui/');
            } else {
                const errEl = document.getElementById('login-error');
                errEl.textContent = 'Invalid password';
                errEl.style.display = 'block';
            }
        } catch (err) {
            const errEl = document.getElementById('login-error');
            errEl.textContent = err.message;
            errEl.style.display = 'block';
        }
    });
}

/**
 * Login form — rendered when session is not authenticated.
 */
function renderLoginForm(container) {
    // Hide sidebar on login page
    const sidebar = document.getElementById('sidebar');
    const hamburger = document.getElementById('hamburger');
    const mobileAppBar = document.getElementById('mobile-app-bar');
    if (sidebar) sidebar.style.display = 'none';
    if (hamburger) hamburger.style.display = 'none';
    if (mobileAppBar) mobileAppBar.style.display = 'none';
    container.style.marginLeft = '0';

    const loginDiv = document.createElement('div');
    loginDiv.className = 'login-container';

    const h1 = document.createElement('h1');
    h1.textContent = 'Octopus Registry';
    loginDiv.appendChild(h1);

    const form = document.createElement('form');
    form.id = 'login-form';

    // Password field with show/hide toggle
    const passWrap = document.createElement('div');
    passWrap.className = 'password-wrap';

    const passInput = document.createElement('input');
    passInput.type = 'password';
    passInput.id = 'login-password';
    passInput.className = 'search-input';
    passInput.placeholder = 'UI password';
    passInput.setAttribute('aria-label', 'UI password');
    passInput.autocomplete = 'current-password';
    passWrap.appendChild(passInput);

    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'password-toggle';
    toggleBtn.textContent = 'Show';
    toggleBtn.addEventListener('click', () => {
        if (passInput.type === 'password') {
            passInput.type = 'text';
            toggleBtn.textContent = 'Hide';
        } else {
            passInput.type = 'password';
            toggleBtn.textContent = 'Show';
        }
    });
    passWrap.appendChild(toggleBtn);

    form.appendChild(passWrap);

    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.style.width = '100%';
    submitBtn.textContent = 'Sign in';
    form.appendChild(submitBtn);

    const errorDiv = document.createElement('div');
    errorDiv.className = 'login-error';
    errorDiv.style.display = 'none';
    form.appendChild(errorDiv);

    loginDiv.appendChild(form);
    container.appendChild(loginDiv);

    // Focus password field
    requestAnimationFrame(() => passInput.focus());

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const password = passInput.value;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Signing in...';
        errorDiv.style.display = 'none';

        try {
            const resp = await fetch('/ui/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'password=' + encodeURIComponent(password),
                credentials: 'same-origin',
                redirect: 'manual',
            });
            if (resp.ok || resp.type === 'opaqueredirect' || resp.status === 302) {
                // Restore sidebar
                if (sidebar) sidebar.style.display = '';
                if (hamburger) hamburger.style.display = '';
                if (mobileAppBar) mobileAppBar.style.display = '';
                container.style.marginLeft = '';
                // Fetch CSRF token after login
                await API.fetchCsrf();
                Router.navigate('/ui/');
            } else {
                errorDiv.textContent = 'Invalid password';
                errorDiv.style.display = 'block';
            }
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.style.display = 'block';
        }
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign in';
    });

    return function cleanup() {
        // Restore sidebar visibility if navigating away
        if (sidebar) sidebar.style.display = '';
        if (hamburger) hamburger.style.display = '';
        if (mobileAppBar) mobileAppBar.style.display = '';
        container.style.marginLeft = '';
    };
}

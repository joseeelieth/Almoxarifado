// ================= Toggle Senha =================
document.addEventListener('DOMContentLoaded', function() {
    const toggles = document.querySelectorAll('.toggle-password');

    toggles.forEach(function(toggle) {
        toggle.addEventListener('click', function() {
            const input = this.previousElementSibling;
            if (input.type === 'password') {
                input.type = 'text';
                this.classList.remove('fa-eye');
                this.classList.add('fa-eye-slash');
            } else {
                input.type = 'password';
                this.classList.remove('fa-eye-slash');
                this.classList.add('fa-eye');
            }
        });
    });
});

// ================= Confirmação de ações =================
document.addEventListener('DOMContentLoaded', function() {
    const confirmForms = document.querySelectorAll('.confirm-action');

    confirmForms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const action = this.getAttribute('data-action') || 'realizar esta ação';
            if (!confirm(`Deseja realmente ${action}?`)) {
                e.preventDefault();
            }
        });
    });
});

// ================= Tooltip Bootstrap =================
document.addEventListener('DOMContentLoaded', function () {
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    tooltipTriggerList.forEach(function (tooltipTriggerEl) {
        new bootstrap.Tooltip(tooltipTriggerEl)
    });
});

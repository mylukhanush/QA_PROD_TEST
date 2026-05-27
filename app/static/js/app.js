/**
 * QA Agent — Frontend JavaScript
 * Handles HTMX events, toast notifications, and shared utilities.
 */

// ── Toast Notifications ──────────────────────────────────────────

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 300ms ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ── HTMX Event Hooks ─────────────────────────────────────────────

document.addEventListener('htmx:afterSwap', (evt) => {
    // Apply fade-in animation to newly swapped content
    const target = evt.detail.target;
    if (target) {
        target.classList.add('fade-in');
    }
});

document.addEventListener('htmx:responseError', (evt) => {
    showToast('Request failed. Please try again.', 'error');
});

// ── Utility: Time Ago ────────────────────────────────────────────

function timeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    return Math.floor(seconds / 86400) + 'd ago';
}

// ── Utility: Format Duration ─────────────────────────────────────

function formatDuration(ms) {
    if (!ms) return '—';
    if (ms < 1000) return ms + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
    return (ms / 60000).toFixed(1) + 'm';
}

// ── Keyboard Shortcuts ───────────────────────────────────────────

document.addEventListener('keydown', (e) => {
    // Ctrl+K or Cmd+K — focus search/situation input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const input = document.getElementById('situation-input');
        if (input) input.focus();
    }
});

// ── Auto-update "time ago" elements ──────────────────────────────

function updateTimeAgo() {
    document.querySelectorAll('[data-time-ago]').forEach(el => {
        el.textContent = timeAgo(el.dataset.timeAgo);
    });
}

// Update every 30 seconds
setInterval(updateTimeAgo, 30000);

// ── Global Test Case Inspector ───────────────────────────────────

async function openTestCaseDetailsModal(tcId) {
    try {
        const resp = await fetch(`/api/test-cases/${tcId}/site-runs`);
        const data = await resp.json();
        
        if (data.sites && data.sites.length > 0) {
            window.location.href = `/runs/${data.sites[0].run_id}`;
        } else {
            alert('No runs found for this test case.');
        }
    } catch (err) {
        console.error('Failed to load test case runs:', err);
        alert('Error loading test case details.');
    }
}

function closeTestCaseDetailsModal() {
    const modal = document.getElementById('test-case-details-modal');
    if (modal) modal.classList.add('hidden');
}

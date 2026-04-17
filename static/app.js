/**
 * PVS-Tracker — Main JavaScript Module
 *
 * Handles:
 *  - Theme toggling (light / dark) with localStorage persistence
 *  - Language switching (RU / EN) with localStorage persistence
 *  - i18n translation engine
 *  - Chart.js initialization with theme-aware colors
 *  - UI helpers (loading spinners, animations)
 */

/* ============================================================
   Theme Management
   ============================================================ */

const ThemeManager = (() => {
    const STORAGE_KEY = 'pvs-tracker-theme';
    const ATTR = 'data-theme';

    function getPreferredTheme() {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) return stored;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute(ATTR, theme);
        localStorage.setItem(STORAGE_KEY, theme);
        if (window.__pvsChart) {
            updateChartTheme(window.__pvsChart, theme);
        }
    }

    function toggle() {
        const current = document.documentElement.getAttribute(ATTR) || getPreferredTheme();
        applyTheme(current === 'dark' ? 'light' : 'dark');
    }

    document.addEventListener('DOMContentLoaded', () => applyTheme(getPreferredTheme()));

    return { toggle, getPreferredTheme, applyTheme };
})();

/* ============================================================
   i18n / Language Management
   ============================================================ */

const I18n = (() => {
    const STORAGE_KEY = 'pvs-tracker-lang';
    const DEFAULT_LANG = 'ru';
    let translations = {};
    let currentLang = DEFAULT_LANG;

    function getPreferredLang() {
        return localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;
    }

    function t(key) {
        return (translations[currentLang] && translations[currentLang][key]) || key;
    }

    function applyLanguage(lang) {
        currentLang = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        document.documentElement.lang = lang;

        // Update all elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach((el) => {
            const key = el.getAttribute('data-i18n');
            const value = t(key);
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                if (el.getAttribute('data-i18n-attr') === 'placeholder') {
                    el.placeholder = value;
                } else {
                    el.value = value;
                }
            } else if (el.tagName === 'LABEL') {
                el.textContent = value;
            } else if (el.tagName === 'OPTION') {
                el.textContent = value;
            } else if (el.tagName === 'BUTTON') {
                // Keep icons inside buttons
                const icons = el.querySelectorAll('i, svg');
                if (icons.length > 0) {
                    // Find text node only
                    el.childNodes.forEach((node) => {
                        if (node.nodeType === Node.TEXT_NODE) {
                            node.textContent = value + ' ';
                        }
                    });
                } else {
                    el.textContent = value;
                }
            } else {
                el.textContent = value;
            }
        });

        // Update placeholders with data-i18n-placeholder
        document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
            el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
        });

        // Update chart legend if exists
        if (window.__pvsChart) {
            updateChartLegend(window.__pvsChart);
        }

        // Update lang toggle button text
        const langBtn = document.getElementById('lang-toggle');
        if (langBtn) {
            langBtn.querySelector('.lang-label').textContent = lang === 'ru' ? 'EN' : 'RU';
            langBtn.title = t('toggle_lang');
        }
    }

    function toggle() {
        const newLang = currentLang === 'ru' ? 'en' : 'ru';
        applyLanguage(newLang);
    }

    // Load translations and init
    async function init() {
        currentLang = getPreferredLang();
        try {
            const resp = await fetch('/static/translations.json');
            translations = await resp.json();
            applyLanguage(currentLang);
        } catch (e) {
            console.warn('Failed to load translations:', e);
        }
    }

    document.addEventListener('DOMContentLoaded', init);

    return { t, toggle, applyLanguage, getPreferredLang };
})();

/* ============================================================
   Chart Helpers
   ============================================================ */

function getChartColors(theme) {
    const isDark = theme === 'dark';
    return {
        gridColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
        tickColor: isDark ? '#8b949e' : '#6c757d',
        legendColor: isDark ? '#e6edf3' : '#212529',
        tooltipBg: isDark ? 'rgba(22,27,34,0.95)' : 'rgba(33,37,41,0.9)',
        tooltipText: isDark ? '#e6edf3' : '#ffffff',
    };
}

function createTrendChart(canvasId, historyData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const ctx = canvas.getContext('2d');
    const theme = document.documentElement.getAttribute('data-theme') || 'light';
    const colors = getChartColors(theme);

    // Build labels: show commit hash + timestamp if available
    const labels = historyData.map((d) => {
        if (d.commit && d.commit !== '—') {
            // Short commit hash (6 chars) + date
            const shortHash = d.commit.substring(0, 6);
            const date = new Date(d.timestamp).toLocaleDateString();
            return `${shortHash} (${date})`;
        }
        return new Date(d.timestamp).toLocaleDateString();
    });
    const newData = historyData.map((d) => d.new);
    const activeData = historyData.map((d) => d.total);
    const fixedData = historyData.map((d) => d.fixed);

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: I18n.t('chart_legend_active'),
                    data: activeData,
                    borderColor: '#0d6efd',
                    backgroundColor: 'rgba(13,110,253,0.08)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#0d6efd',
                    tension: 0.3,
                    fill: true,
                },
                {
                    label: I18n.t('chart_legend_new'),
                    data: newData,
                    borderColor: '#dc3545',
                    backgroundColor: 'rgba(220,53,69,0.08)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#dc3545',
                    tension: 0.3,
                    fill: true,
                },
                {
                    label: I18n.t('chart_legend_fixed'),
                    data: fixedData,
                    borderColor: '#198754',
                    backgroundColor: 'rgba(25,135,84,0.08)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#198754',
                    tension: 0.3,
                    fill: true,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index',
            },
            plugins: {
                legend: {
                    labels: {
                        color: colors.legendColor,
                        font: { size: 13, weight: '500' },
                        padding: 20,
                        usePointStyle: true,
                        pointStyleWidth: 12,
                    },
                },
                tooltip: {
                    backgroundColor: colors.tooltipBg,
                    titleColor: colors.tooltipText,
                    bodyColor: colors.tooltipText,
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 12,
                    titleFont: { size: 13, weight: '600' },
                    bodyFont: { size: 12 },
                    displayColors: true,
                    boxPadding: 4,
                    callbacks: {
                        title: function (items) {
                            if (items.length > 0) {
                                const idx = items[0].dataIndex;
                                const d = historyData[idx];
                                const parts = [];
                                if (d.branch && d.branch !== '—') {
                                    parts.push(`${I18n.t('chart_branch_label')}: ${d.branch}`);
                                }
                                if (d.commit && d.commit !== '—') {
                                    parts.push(`${I18n.t('chart_commit_label')}: ${d.commit}`);
                                }
                                parts.push(`${I18n.t('chart_date_label')}: ${new Date(d.timestamp).toLocaleString()}`);
                                return parts.join(' | ');
                            }
                            return '';
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { color: colors.gridColor },
                    ticks: {
                        color: colors.tickColor,
                        font: { size: 11 },
                        maxRotation: 45,
                        minRotation: 0,
                    },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: colors.gridColor },
                    ticks: {
                        color: colors.tickColor,
                        font: { size: 11 },
                        stepSize: 1,
                    },
                },
            },
            animation: {
                duration: 800,
                easing: 'easeOutQuart',
            },
        },
    });

    window.__pvsChart = chart;
    return chart;
}

function updateChartTheme(chart, theme) {
    if (!chart) return;
    const colors = getChartColors(theme);

    chart.options.scales.x.grid.color = colors.gridColor;
    chart.options.scales.x.ticks.color = colors.tickColor;
    chart.options.scales.y.grid.color = colors.gridColor;
    chart.options.scales.y.ticks.color = colors.tickColor;
    chart.options.plugins.legend.labels.color = colors.legendColor;
    chart.options.plugins.tooltip.backgroundColor = colors.tooltipBg;
    chart.options.plugins.tooltip.titleColor = colors.tooltipText;
    chart.options.plugins.tooltip.bodyColor = colors.tooltipText;

    chart.update('none');
}

function updateChartLegend(chart) {
    if (!chart || !chart.data || !chart.data.datasets) return;
    const labels = ['chart_legend_active', 'chart_legend_new', 'chart_legend_fixed'];
    chart.data.datasets.forEach((ds, i) => {
        if (labels[i]) {
            ds.label = I18n.t(labels[i]);
        }
    });
    chart.update('none');
}

/* ============================================================
   UI Helpers
   ============================================================ */

// Add fade-in animation to elements with .fade-in class
function initFadeIn() {
    document.querySelectorAll('.fade-in').forEach((el, i) => {
        el.style.animationDelay = `${i * 0.05}s`;
    });
}

// Show a Bootstrap toast programmatically
function showToast(message, type = 'info') {
    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-bg-${type} border-0 show`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>`;

    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;';
        document.body.appendChild(container);
    }
    container.appendChild(toastEl);

    setTimeout(() => {
        toastEl.remove();
    }, 4000);
}

// Format a number with locale separators
function formatNumber(n) {
    return new Intl.NumberFormat().format(n);
}

// Animate a counter from 0 to target
function animateCounter(element, target, duration = 600) {
    const start = 0;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // ease-out quad
        const eased = 1 - (1 - progress) * (1 - progress);
        const current = Math.round(start + (target - start) * eased);
        element.textContent = formatNumber(current);
        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

// Initialize counters with .animate-count attribute
function initAnimatedCounters() {
    document.querySelectorAll('.animate-count').forEach((el) => {
        const target = parseInt(el.dataset.target || el.textContent, 10);
        if (!isNaN(target)) {
            el.textContent = '0';
            animateCounter(el, target);
        }
    });
}

/* ============================================================
   HTMX Event Enhancements
   ============================================================ */

document.addEventListener('htmx:afterOnLoad', (evt) => {
    // Re-init fade-in on HTMX swaps
    initFadeIn();
    initAnimatedCounters();
});

document.addEventListener('htmx:beforeRequest', (evt) => {
    // Could add global loading spinner here
});

document.addEventListener('htmx:afterRequest', (evt) => {
    if (evt.detail.successful) {
        const response = evt.detail.xhr.responseText;
        if (response && response.includes('"ignored"')) {
            showToast(I18n.t('toast_ignored'), 'success');
        }
    }
});

/* ============================================================
Code Viewer Manager (Scroll Sync + Prism + Target Highlight)
============================================================ */
const CodeViewer = (() => {
  let isInitialized = false;

  function syncScroll() {
    const master = document.getElementById('sq-code-scroll');
    const gutter = document.getElementById('sq-line-numbers');
    const annotations = document.getElementById('sq-annotations-panel');
    if (!master || !gutter || !annotations) return;

    // Удаляем старые слушатели (чтобы не дублировать при HTMX)
    master.replaceWith(master.cloneNode(true));
    const newMaster = document.getElementById('sq-code-scroll');
    
    newMaster.addEventListener('scroll', () => {
      gutter.scrollTop = newMaster.scrollTop;
      annotations.scrollTop = newMaster.scrollTop;
    });
  }

  function highlightCode() {
    const codeBlock = document.querySelector('.sq-code-block code');
    if (!codeBlock || typeof Prism === 'undefined') return;

    // Сбрасываем, если Prism уже подсветил
    if (codeBlock.classList.contains('language-') || codeBlock.getAttribute('data-highlighted')) {
      codeBlock.removeAttribute('data-highlighted');
    }
    
    Prism.highlightElement(codeBlock);
  }

  function scrollToTarget() {
    const target = document.querySelector('.sq-code-block').dataset.target;
    if (!target) return;
    
    const targetEl = document.querySelector(`.sq-line-num[data-line="${target}"]`);
    if (targetEl) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Синхронизируем скролл сразу после плавной прокрутки
      const master = document.getElementById('sq-code-scroll');
      if (master) master.scrollTop = targetEl.offsetTop - (master.clientHeight / 2);
    }
  }

  function init() {
    if (isInitialized) return;
    const viewer = document.querySelector('.sq-code-viewer');
    if (!viewer) return;

    highlightCode();
    syncScroll();
    
    // Даем браузеру отрендерить линии, потом скроллим к цели
    requestAnimationFrame(() => requestAnimationFrame(scrollToTarget));
    isInitialized = true;
  }

  function reset() { isInitialized = false; }

  // Hook into HTMX swaps
  document.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target.closest('.sq-code-viewer') || e.detail.target.querySelector('.sq-code-viewer')) {
      reset();
      setTimeout(init, 50); // Небольшая задержка для гарантированного рендера
    }
  });

  document.addEventListener('DOMContentLoaded', init);

  return { init, reset };
})();

/* ============================================================
   Init on DOM Ready
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    initFadeIn();
    initAnimatedCounters();
});

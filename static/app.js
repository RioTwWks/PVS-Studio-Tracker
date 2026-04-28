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
            // 🔑 ПРОВЕРКА: если элемент удалён из DOM — пропускаем
            if (!el || !document.contains(el)) return;
            
            const key = el.getAttribute('data-i18n');
            const value = t(key);
            
            try {
                if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                    if (el.getAttribute('data-i18n-attr') === 'placeholder') {
                        el.placeholder = value;
                    } else {
                        el.value = value;
                    }
                } else if (el.tagName === 'LABEL' || el.tagName === 'OPTION' || el.tagName === 'BUTTON') {
                    // Для кнопок сохраняем иконки
                    if (el.tagName === 'BUTTON') {
                        const icons = el.querySelectorAll('i, svg');
                        if (icons.length > 0) {
                            el.childNodes.forEach((node) => {
                                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
                                    node.textContent = value + ' ';
                                }
                            });
                        } else {
                            el.textContent = value;
                        }
                    } else {
                        el.textContent = value;
                    }
                } else {
                    // 🔑 Безопасная установка: проверяем, что элемент ещё в DOM
                    if (el.textContent !== undefined) {
                        el.textContent = value;
                    }
                }
            } catch (e) {
                console.warn(`i18n error for element ${key}:`, e);
            }
        });

        // Update placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
            if (el && el.placeholder !== undefined) {
                el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
            }
        });

        // Update chart legend if exists
        if (window.__pvsChart) {
            updateChartLegend(window.__pvsChart);
        }

        // Update lang toggle button text — с проверкой
        const langBtn = document.getElementById('lang-toggle');
        if (langBtn) {
            const label = langBtn.querySelector('.lang-label');
            if (label) {
                label.textContent = lang === 'ru' ? 'EN' : 'RU';
            }
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
    const isDark = theme === 'dark';

    const activeGradient = ctx.createLinearGradient(0, 0, 0, 360);
    activeGradient.addColorStop(0, isDark ? 'rgba(88, 166, 255, 0.28)' : 'rgba(13, 110, 253, 0.18)');
    activeGradient.addColorStop(1, 'rgba(13, 110, 253, 0)');

    const newGradient = ctx.createLinearGradient(0, 0, 0, 360);
    newGradient.addColorStop(0, isDark ? 'rgba(255, 123, 114, 0.24)' : 'rgba(220, 53, 69, 0.14)');
    newGradient.addColorStop(1, 'rgba(220, 53, 69, 0)');

    const fixedGradient = ctx.createLinearGradient(0, 0, 0, 360);
    fixedGradient.addColorStop(0, isDark ? 'rgba(63, 185, 80, 0.22)' : 'rgba(25, 135, 84, 0.12)');
    fixedGradient.addColorStop(1, 'rgba(25, 135, 84, 0)');

    // Build labels: show commit hash + timestamp if available
    const labels = historyData.map((d) => {
        if (d.commit && d.commit !== '—') {
            const date = new Date(d.timestamp).toLocaleDateString();
            return date;
        }
        return new Date(d.timestamp).toLocaleDateString();
    });
    const newData = historyData.map((d) => d.new);
    const activeData = historyData.map((d) => d.total);
    const fixedData = historyData.map((d) => d.fixed);
    const maxValue = Math.max(1, ...newData, ...activeData, ...fixedData);

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: I18n.t('chart_legend_active'),
                    data: activeData,
                    borderColor: isDark ? '#58a6ff' : '#0d6efd',
                    backgroundColor: activeGradient,
                    borderWidth: 3,
                    pointRadius: 3,
                    pointHoverRadius: 7,
                    pointBackgroundColor: isDark ? '#0d1117' : '#ffffff',
                    pointBorderColor: isDark ? '#58a6ff' : '#0d6efd',
                    pointBorderWidth: 2,
                    tension: 0.36,
                    fill: true,
                },
                {
                    label: I18n.t('chart_legend_new'),
                    data: newData,
                    borderColor: isDark ? '#ff7b72' : '#dc3545',
                    backgroundColor: newGradient,
                    borderWidth: 2.5,
                    pointRadius: 3,
                    pointHoverRadius: 7,
                    pointBackgroundColor: isDark ? '#0d1117' : '#ffffff',
                    pointBorderColor: isDark ? '#ff7b72' : '#dc3545',
                    pointBorderWidth: 2,
                    tension: 0.36,
                    fill: true,
                },
                {
                    label: I18n.t('chart_legend_fixed'),
                    data: fixedData,
                    borderColor: isDark ? '#3fb950' : '#198754',
                    backgroundColor: fixedGradient,
                    borderWidth: 2.5,
                    pointRadius: 3,
                    pointHoverRadius: 7,
                    pointBackgroundColor: isDark ? '#0d1117' : '#ffffff',
                    pointBorderColor: isDark ? '#3fb950' : '#198754',
                    pointBorderWidth: 2,
                    tension: 0.36,
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
            layout: {
                padding: { top: 8, right: 12, bottom: 0, left: 4 },
            },
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: {
                    backgroundColor: colors.tooltipBg,
                    titleColor: colors.tooltipText,
                    bodyColor: colors.tooltipText,
                    borderColor: isDark ? 'rgba(255,255,255,0.12)' : 'rgba(13,110,253,0.16)',
                    borderWidth: 1,
                    cornerRadius: 10,
                    padding: 14,
                    titleFont: { size: 13, weight: '600' },
                    bodyFont: { size: 12, weight: '500' },
                    displayColors: true,
                    boxPadding: 6,
                    caretPadding: 8,
                    callbacks: {
                        title: function (items) {
                            if (items.length > 0) {
                                const idx = items[0].dataIndex;
                                const d = historyData[idx];
                                const parts = [new Date(d.timestamp).toLocaleString()];
                                if (d.commit && d.commit.length > 0) {
                                    parts.push(d.commit.substring(0, 8));
                                }
                                return parts.join('  |  ');
                            }
                            return '';
                        },
                        afterTitle: function (items) {
                            if (items.length === 0) return '';
                            const d = historyData[items[0].dataIndex];
                            return d.branch && d.branch.length > 0 ? `${I18n.t('chart_branch_label')}: ${d.branch}` : '';
                        },
                        label: function (item) {
                            return `${item.dataset.label}: ${item.formattedValue}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    border: { display: false },
                    ticks: {
                        color: colors.tickColor,
                        font: { size: 11, weight: '500' },
                        maxRotation: 0,
                        minRotation: 0,
                        maxTicksLimit: 8,
                    },
                },
                y: {
                    beginAtZero: true,
                    suggestedMax: Math.ceil(maxValue * 1.15),
                    grid: {
                        color: colors.gridColor,
                        drawTicks: false,
                    },
                    border: { display: false },
                    ticks: {
                        color: colors.tickColor,
                        font: { size: 11 },
                        padding: 10,
                        precision: 0,
                        // stepSize удалён — Chart.js подберёт автоматически
                        callback: function(value) {
                            // Показывать только целые числа
                            return Number.isInteger(value) ? value : null;
                        },
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
    initTrendChartFilters(chart);
    return chart;
}

function initTrendChartFilters(chart) {
    const controls = document.querySelectorAll('.sq-legend-filter[data-dataset-index]');
    if (!chart || controls.length === 0) return;

    controls.forEach((control) => {
        const index = Number(control.dataset.datasetIndex);
        const visible = chart.isDatasetVisible(index);
        control.classList.toggle('active', visible);
        control.setAttribute('aria-pressed', String(visible));

        control.onclick = () => {
            const visibleCount = chart.data.datasets.filter((_, datasetIndex) => chart.isDatasetVisible(datasetIndex)).length;
            const isVisible = chart.isDatasetVisible(index);

            if (isVisible && visibleCount === 1) {
                return;
            }

            chart.setDatasetVisibility(index, !isVisible);
            chart.update();
            control.classList.toggle('active', !isVisible);
            control.setAttribute('aria-pressed', String(!isVisible));
        };
    });
}

function updateChartTheme(chart, theme) {
    if (!chart) return;
    const colors = getChartColors(theme);

    chart.options.scales.x.grid.color = colors.gridColor;
    chart.options.scales.x.ticks.color = colors.tickColor;
    chart.options.scales.y.grid.color = colors.gridColor;
    chart.options.scales.y.ticks.color = colors.tickColor;
    if (chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = colors.legendColor;
    }
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
  let activeViewer = null;

  function getViewer(root) {
    if (!root) return document.querySelector('.sq-code-viewer');
    if (root.classList && root.classList.contains('sq-code-viewer')) return root;
    return root.querySelector ? root.querySelector('.sq-code-viewer') : null;
  }

  function syncScroll(viewer) {
    const master = viewer.querySelector('.sq-code-scroll-area');
    const gutter = viewer.querySelector('.sq-line-numbers');
    const annotations = viewer.querySelector('.sq-annotations-panel');
    if (!master) return;

    if (master.__pvsScrollHandler) {
      master.removeEventListener('scroll', master.__pvsScrollHandler);
    }

    master.__pvsScrollHandler = () => {
      if (gutter) gutter.scrollTop = master.scrollTop;
      if (annotations) annotations.scrollTop = master.scrollTop;
    };
    master.addEventListener('scroll', master.__pvsScrollHandler, { passive: true });
    master.__pvsScrollHandler();

    [gutter, annotations].forEach((sidePanel) => {
      if (!sidePanel) return;

      if (sidePanel.__pvsWheelHandler) {
        sidePanel.removeEventListener('wheel', sidePanel.__pvsWheelHandler);
      }

      sidePanel.__pvsWheelHandler = (event) => {
        master.scrollTop += event.deltaY;
        master.scrollLeft += event.deltaX;
        if (master.__pvsScrollHandler) master.__pvsScrollHandler();
        event.preventDefault();
      };
      sidePanel.addEventListener('wheel', sidePanel.__pvsWheelHandler, { passive: false });
    });
  }

  function highlightCode(viewer) {
    if (typeof Prism === 'undefined') return;
    viewer.querySelectorAll('.sq-code-line-code').forEach((codeBlock) => {
      codeBlock.removeAttribute('data-highlighted');
      Prism.highlightElement(codeBlock);
    });
  }

  function scrollToTarget(viewer) {
    const codeBlock = viewer.querySelector('.sq-code-block');
    const target = codeBlock ? codeBlock.dataset.target : null;
    if (!target) return;
    
    const targetEl = viewer.querySelector(`.sq-line-num[data-line="${target}"]`);
    if (targetEl) {
      // Синхронизируем скролл сразу после плавной прокрутки
      const master = viewer.querySelector('.sq-code-scroll-area');
      if (master) {
        master.scrollTop = Math.max(0, targetEl.offsetTop - (master.clientHeight / 2));
        if (master.__pvsScrollHandler) master.__pvsScrollHandler();
      }
    }
  }

  function init(root) {
    const viewer = getViewer(root);
    if (!viewer) return;
    if (isInitialized && activeViewer === viewer) return;

    activeViewer = viewer;
    highlightCode(viewer);
    syncScroll(viewer);
    
    // Даем браузеру отрендерить линии, потом скроллим к цели
    requestAnimationFrame(() => requestAnimationFrame(() => scrollToTarget(viewer)));
    isInitialized = true;
  }

  function reset() {
    isInitialized = false;
    activeViewer = null;
  }

  document.addEventListener('DOMContentLoaded', () => init());

  return { init, reset };
})();

/* ============================================================
   Init on DOM Ready
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    initFadeIn();
    initAnimatedCounters();
});

/* ============================================================
HTMX Event Enhancements — Unified Handler
============================================================ */
document.addEventListener('htmx:afterSwap', (e) => {
    // Re-highlight code blocks inserted by HTMX
    if (e.detail.target.closest('.sq-inline-code-content') || 
        e.detail.target.classList.contains('sq-inline-code-content')) {
        
        // Wait for content to be in DOM, then highlight
        setTimeout(() => {
            const codeBlocks = e.detail.target.querySelectorAll('code[class*="language-"]');
            codeBlocks.forEach(block => {
                if (typeof Prism !== 'undefined') {
                    Prism.highlightElement(block);
                }
            });
        }, 10);
    }
});

// 🔑 Делаем CodeViewer доступным для других скриптов
window.CodeViewer = CodeViewer;

async function toggleInlineCode(btn, issueId) {
    const row = document.getElementById('code-row-' + issueId);
    if (!row) return;

    const isVisible = row.style.display === 'table-row';
    if (isVisible) {
        // Закрыть и вернуть кнопке исходный вид
        row.style.display = 'none';
        btn.innerHTML = '<i class="bi bi-code-slash"></i> Code';
        return;
    }

    // Показать строку и сменить кнопку на Close
    row.style.display = 'table-row';
    btn.innerHTML = '<i class="bi bi-x"></i> Close';

    const content = document.getElementById('code-content-' + issueId);
    if (content && content.dataset.loaded === 'true') {
        // Код уже загружен, просто показали
        return;
    }

    // Загружаем код
    const filePath = btn.dataset.filePath;
    const line = btn.dataset.line;
    const projectId = btn.dataset.projectId;
    const runId = btn.dataset.runId;

    content.innerHTML = '<div class="sq-loading">Loading code...</div>';

    try {
        const params = new URLSearchParams({
            project_id: projectId,
            file_path: filePath,
            line: line,
            context: 10
        });
        if (runId) params.append('run_id', runId);
        const resp = await fetch(`/ui/file?${params.toString()}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const html = await resp.text();
        content.innerHTML = html;
        content.dataset.loaded = 'true';

        if (window.CodeViewer) {
            window.CodeViewer.reset();
            window.CodeViewer.init(content);
        }

        // Подсветка синтаксиса
        if (typeof Prism !== 'undefined') {
            content.querySelectorAll('.sq-code-line-code').forEach(el => Prism.highlightElement(el));
        }
    } catch (e) {
        content.innerHTML = `<div class="sq-alert sq-alert-danger">Error: ${e.message}</div>`;
    }
}

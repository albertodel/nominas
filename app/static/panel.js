// Gráficas del panel (Chart.js, servido localmente desde /static/vendor).
(() => {
  const datos = JSON.parse(document.getElementById('datos').textContent);
  if (!window.Chart) {
    document.querySelectorAll('.chart-box').forEach(b =>
      b.innerHTML = '<p class="muted small">No se ha podido cargar Chart.js (/static/vendor).</p>');
    return;
  }
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const eur = v => v.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' });
  let graficas = [];

  function leyenda(el, items) {
    el.innerHTML = '';
    items.forEach(([nombre, color]) => {
      const s = document.createElement('span');
      s.innerHTML = `<i style="background:${color}"></i>`;
      s.append(nombre);
      el.appendChild(s);
    });
  }

  function dibujar() {
    graficas.forEach(g => g.destroy());
    graficas = [];
    const series = [css('--s1'), css('--s2'), css('--s3'), css('--s4')];
    const texto2 = css('--text-2'), borde = css('--border'), fondo = css('--surface');
    Chart.defaults.font.family = css('--sans');
    Chart.defaults.color = texto2;
    Chart.defaults.animation.duration = 350;
    const ejes = (fmt) => ({
      x: { stacked: true, grid: { display: false }, border: { color: borde } },
      y: { stacked: true, beginAtZero: true, grid: { color: borde }, border: { display: false },
           ticks: { callback: fmt, maxTicksLimit: 6 } },
    });
    const tooltip = (fmt) => ({
      backgroundColor: fondo, titleColor: css('--text'), bodyColor: texto2,
      borderColor: borde, borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
      callbacks: { label: c => ` ${c.dataset.label}: ${c.parsed.y == null ? '—' : fmt(c.parsed.y)}` },
    });

    // 1) Barras apiladas: Líquido + IRPF + S.S. (+ otras) = total devengado del mes
    const nombres = Object.keys(datos.barras);
    const ultimo = nombres.length - 1;
    const sets = nombres.map((n, i) => ({
      label: n, data: datos.barras[n], backgroundColor: series[i],
      borderColor: fondo, borderWidth: { top: i === ultimo ? 0 : 2 },
      borderSkipped: false,
      borderRadius: i === ultimo ? { topLeft: 4, topRight: 4 } : 0,
      maxBarThickness: 34,
    }));
    leyenda(document.getElementById('leyenda'), nombres.map((n, i) => [n, series[i]]));
    graficas.push(new Chart(document.getElementById('g-barras'), {
      type: 'bar',
      data: { labels: datos.meses, datasets: sets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { ...tooltip(eur), callbacks: {
            ...tooltip(eur).callbacks,
            footer: items => 'Total devengado: ' + eur(items.reduce((a, i) => a + i.parsed.y, 0)),
          } },
        },
        scales: ejes(v => v.toLocaleString('es-ES') + ' €'),
      },
    }));

    // 2) % IRPF por empresa
    const empresas = Object.keys(datos.irpf_pct).filter(e => datos.irpf_pct[e].some(v => v !== null));
    const card = document.getElementById('card-irpf');
    if (!empresas.length) { card.hidden = true; return; }
    leyenda(document.getElementById('leyenda-irpf'), empresas.map((e, i) => [e, series[i % 4]]));
    const valores = empresas.flatMap(e => datos.irpf_pct[e].filter(v => v !== null));
    const ej = ejes(v => v.toLocaleString('es-ES') + ' %');
    ej.x.stacked = ej.y.stacked = false;
    ej.y.beginAtZero = false;
    ej.y.suggestedMin = Math.max(0, Math.floor(Math.min(...valores) - 2));
    ej.y.suggestedMax = Math.ceil(Math.max(...valores) + 2);
    graficas.push(new Chart(document.getElementById('g-irpf'), {
      type: 'line',
      data: { labels: datos.meses, datasets: empresas.map((e, i) => ({
        label: e, data: datos.irpf_pct[e], borderColor: series[i % 4], backgroundColor: series[i % 4],
        borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: fondo,
        pointBorderWidth: 2, spanGaps: true, tension: 0,
      })) },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false },
                   tooltip: tooltip(v => v.toLocaleString('es-ES', { minimumFractionDigits: 2 }) + ' %') },
        scales: ej,
      },
    }));
  }

  dibujar();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', dibujar);
})();

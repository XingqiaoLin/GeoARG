<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GeoARG — Geometry-Enhanced ARG Discovery</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0a0b;
  --surface:#111113;
  --surface2:#19191d;
  --surface3:#222228;
  --border:#2a2a32;
  --border-light:#3a3a44;
  --text:#e8e8ed;
  --text-secondary:#9898a6;
  --text-muted:#68687a;
  --accent:#6ee7b7;
  --accent2:#34d399;
  --accent-dim:rgba(110,231,183,0.08);
  --accent-dim2:rgba(110,231,183,0.15);
  --blue:#60a5fa;
  --purple:#a78bfa;
  --amber:#fbbf24;
  --rose:#fb7185;
  --cyan:#22d3ee;
  --mono:'JetBrains Mono',monospace;
  --sans:'Plus Jakarta Sans',sans-serif;
  --serif:'Instrument Serif',serif;
  --radius:10px;
  --radius-lg:16px;
}
html{scroll-behavior:smooth;background:var(--bg);color:var(--text);font-family:var(--sans)}
body{min-height:100vh;overflow-x:hidden}

/* ─── Hero ─── */
.hero{
  position:relative;
  padding:80px 0 60px;
  text-align:center;
  overflow:hidden;
}
.hero::before{
  content:'';position:absolute;inset:0;
  background:
    radial-gradient(ellipse 600px 400px at 50% 0%,rgba(110,231,183,0.06),transparent),
    radial-gradient(ellipse 400px 300px at 80% 20%,rgba(96,165,250,0.04),transparent);
  pointer-events:none;
}
.hero-glow{
  position:absolute;top:-200px;left:50%;transform:translateX(-50%);
  width:800px;height:400px;
  background:radial-gradient(circle,rgba(110,231,183,0.07) 0%,transparent 70%);
  filter:blur(80px);pointer-events:none;
}
.hero-label{
  display:inline-flex;align-items:center;gap:8px;
  font-family:var(--mono);font-size:13px;font-weight:500;
  color:var(--accent);letter-spacing:0.5px;
  margin-bottom:24px;opacity:0;animation:fadeUp .6s .1s forwards;
}
.hero-label svg{width:18px;height:18px}

.hero h1{
  font-family:var(--sans);font-size:clamp(48px,7vw,80px);font-weight:800;
  letter-spacing:-2.5px;line-height:1;
  color:#fff;margin-bottom:12px;
  opacity:0;animation:fadeUp .6s .2s forwards;
}
.hero h1 span{
  background:linear-gradient(135deg,var(--accent),var(--blue));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.hero-subtitle{
  font-family:var(--serif);font-style:italic;
  font-size:clamp(18px,2.5vw,24px);color:var(--text-secondary);
  max-width:700px;margin:0 auto 36px;line-height:1.5;
  opacity:0;animation:fadeUp .6s .3s forwards;
}

/* ─── Badges ─── */
.badges{
  display:flex;flex-wrap:wrap;justify-content:center;gap:10px;
  margin-bottom:20px;
  opacity:0;animation:fadeUp .6s .4s forwards;
}
.badge{
  display:inline-flex;align-items:center;
  border-radius:8px;overflow:hidden;
  font-family:var(--mono);font-size:12.5px;font-weight:500;
  border:1px solid var(--border);
  background:var(--surface);
  transition:border-color .2s;
}
.badge:hover{border-color:var(--border-light)}
.badge-label{
  padding:5px 10px;
  background:var(--surface2);
  color:var(--text-secondary);
  display:flex;align-items:center;gap:5px;
}
.badge-label svg{width:14px;height:14px;opacity:.7}
.badge-value{padding:5px 10px;font-weight:600}
.badge-value.green{color:var(--accent)}
.badge-value.blue{color:var(--blue)}
.badge-value.purple{color:var(--purple)}
.badge-value.amber{color:var(--amber)}
.badge-value.rose{color:var(--rose)}
.badge-value.cyan{color:var(--cyan)}

/* ─── Callout ─── */
.callout{
  max-width:700px;margin:0 auto;padding:14px 20px;
  border-left:3px solid var(--accent);
  background:var(--accent-dim);
  border-radius:0 var(--radius) var(--radius) 0;
  font-size:14.5px;color:var(--text-secondary);line-height:1.6;
  opacity:0;animation:fadeUp .6s .5s forwards;
}
.callout a{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--accent-dim2)}
.callout a:hover{border-color:var(--accent)}

.divider{
  width:100%;max-width:900px;margin:0 auto;
  height:1px;
  background:linear-gradient(90deg,transparent,var(--border-light),transparent);
}

/* ─── Container ─── */
.container{max-width:900px;margin:0 auto;padding:0 24px}

/* ─── Section ─── */
.section{padding:56px 0}
.section-header{
  display:flex;align-items:center;gap:14px;
  margin-bottom:28px;
}
.section-icon{
  width:42px;height:42px;border-radius:12px;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;
}
.section-icon svg{width:22px;height:22px}
.section-icon.green{background:rgba(110,231,183,0.1);color:var(--accent)}
.section-icon.blue{background:rgba(96,165,250,0.1);color:var(--blue)}
.section-icon.purple{background:rgba(167,139,250,0.1);color:var(--purple)}
.section-icon.amber{background:rgba(251,191,36,0.1);color:var(--amber)}
.section-icon.rose{background:rgba(251,113,133,0.1);color:var(--rose)}
.section-icon.cyan{background:rgba(34,211,238,0.1);color:var(--cyan)}

.section-title{
  font-size:28px;font-weight:800;letter-spacing:-1px;
  color:#fff;
}
.section-title::after{
  content:'';display:block;width:40px;height:3px;
  border-radius:2px;margin-top:8px;
}
.section-icon.green ~ .section-title::after{background:var(--accent)}
.section-icon.blue ~ .section-title::after{background:var(--blue)}
.section-icon.purple ~ .section-title::after{background:var(--purple)}
.section-icon.amber ~ .section-title::after{background:var(--amber)}
.section-icon.rose ~ .section-title::after{background:var(--rose)}
.section-icon.cyan ~ .section-title::after{background:var(--cyan)}

/* ─── Prose ─── */
.prose{font-size:15.5px;line-height:1.75;color:var(--text-secondary)}
.prose strong{color:var(--text);font-weight:600}
.prose a{color:var(--accent);text-decoration:none;border-bottom:1px dashed var(--accent-dim2)}
.prose a:hover{border-bottom-style:solid}
.prose p+p{margin-top:16px}

/* ─── Feature Cards ─── */
.feature-grid{
  display:grid;grid-template-columns:repeat(3,1fr);gap:16px;
  margin-top:24px;
}
.feature-card{
  padding:24px 20px;border-radius:var(--radius-lg);
  background:var(--surface);border:1px solid var(--border);
  transition:border-color .25s,transform .25s;
}
.feature-card:hover{border-color:var(--border-light);transform:translateY(-2px)}
.feature-card-icon{
  width:36px;height:36px;border-radius:10px;
  display:flex;align-items:center;justify-content:center;
  margin-bottom:14px;font-size:18px;
}
.feature-card h3{font-size:15px;font-weight:700;color:#fff;margin-bottom:8px}
.feature-card p{font-size:13.5px;color:var(--text-muted);line-height:1.55}

/* ─── Architecture Box ─── */
.arch-box{
  padding:32px;border-radius:var(--radius-lg);
  background:var(--surface);border:1px solid var(--border);
  margin-top:24px;
}
.arch-table{width:100%;border-collapse:collapse;margin-bottom:28px}
.arch-table th{
  text-align:left;padding:10px 14px;font-size:12px;font-weight:600;
  text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);
  border-bottom:1px solid var(--border);
}
.arch-table td{
  padding:12px 14px;font-size:14px;color:var(--text-secondary);
  border-bottom:1px solid var(--border);vertical-align:top;
}
.arch-table td:first-child{font-weight:600;color:var(--text);white-space:nowrap;font-family:var(--mono);font-size:13px}
.arch-table tr:last-child td{border-bottom:none}

.formula-block{
  padding:20px 24px;border-radius:var(--radius);
  background:var(--surface2);border:1px solid var(--border);
  font-family:var(--mono);font-size:13px;
  color:var(--text-secondary);overflow-x:auto;
  line-height:1.8;
}
.formula-block .label{color:var(--accent);font-weight:600}
.formula-block .math{color:var(--text)}

/* ─── Results Tables ─── */
.results-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:24px}
.result-panel{
  padding:24px;border-radius:var(--radius-lg);
  background:var(--surface);border:1px solid var(--border);
}
.result-panel h3{
  font-size:14px;font-weight:700;color:var(--text);
  margin-bottom:16px;display:flex;align-items:center;gap:8px;
}
.result-panel h3 .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.result-panel table{width:100%;border-collapse:collapse}
.result-panel th{
  text-align:left;padding:8px 10px;font-size:11.5px;font-weight:600;
  text-transform:uppercase;letter-spacing:.8px;color:var(--text-muted);
  border-bottom:1px solid var(--border);
}
.result-panel td{
  padding:8px 10px;font-size:13.5px;color:var(--text-secondary);
  border-bottom:1px solid rgba(42,42,50,0.5);font-family:var(--mono);
}
.result-panel tr.highlight td{color:var(--accent);font-weight:600}
.result-panel tr:last-child td{border-bottom:none}

.result-full{grid-column:1/-1}

/* ─── Code Block ─── */
.code-block{
  margin-top:20px;border-radius:var(--radius-lg);overflow:hidden;
  border:1px solid var(--border);
}
.code-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 16px;background:var(--surface2);
  border-bottom:1px solid var(--border);
}
.code-dots{display:flex;gap:6px}
.code-dots span{width:10px;height:10px;border-radius:50%;background:var(--surface3);border:1px solid var(--border)}
.code-lang{font-family:var(--mono);font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px}
.code-body{
  padding:20px;background:var(--surface);
  font-family:var(--mono);font-size:13px;line-height:1.7;
  color:var(--text-secondary);overflow-x:auto;white-space:pre;
}
.code-body .cmd{color:var(--accent)}
.code-body .flag{color:var(--blue)}
.code-body .str{color:var(--amber)}
.code-body .comment{color:var(--text-muted);font-style:italic}

/* ─── Argument Table ─── */
.arg-table{
  width:100%;border-collapse:collapse;margin-top:20px;
  font-size:13.5px;
}
.arg-table th{
  text-align:left;padding:10px 14px;font-size:11.5px;font-weight:600;
  text-transform:uppercase;letter-spacing:.8px;color:var(--text-muted);
  border-bottom:1px solid var(--border);background:var(--surface);
}
.arg-table td{
  padding:10px 14px;border-bottom:1px solid var(--border);
  color:var(--text-secondary);vertical-align:top;
}
.arg-table td:first-child{font-family:var(--mono);font-size:12.5px;color:var(--accent);white-space:nowrap}
.arg-table td:nth-child(2){font-family:var(--mono);font-size:12.5px;color:var(--text-muted)}
.arg-table tr:last-child td{border-bottom:none}

/* ─── Tree ─── */
.tree{
  padding:24px;border-radius:var(--radius-lg);
  background:var(--surface);border:1px solid var(--border);
  margin-top:20px;
  font-family:var(--mono);font-size:13px;line-height:1.9;
  color:var(--text-muted);
}
.tree .folder{color:var(--blue);font-weight:600}
.tree .file{color:var(--text-secondary)}
.tree .desc{color:var(--text-muted);font-style:italic}

/* ─── Web Server Card ─── */
.server-card{
  margin-top:24px;padding:28px 32px;border-radius:var(--radius-lg);
  background:linear-gradient(135deg,rgba(110,231,183,0.06),rgba(96,165,250,0.04));
  border:1px solid var(--accent-dim2);
  display:flex;align-items:center;gap:24px;
}
.server-card-icon{
  width:56px;height:56px;border-radius:14px;
  background:var(--accent-dim2);
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
}
.server-card-icon svg{width:28px;height:28px;color:var(--accent)}
.server-card h3{font-size:16px;font-weight:700;color:#fff;margin-bottom:6px}
.server-card p{font-size:13.5px;color:var(--text-secondary);line-height:1.55;margin-bottom:10px}
.server-card a.btn{
  display:inline-flex;align-items:center;gap:6px;
  padding:8px 18px;border-radius:8px;
  background:var(--accent);color:var(--bg);
  font-size:13px;font-weight:700;text-decoration:none;
  transition:opacity .2s;
}
.server-card a.btn:hover{opacity:.85}
.server-card a.btn svg{width:14px;height:14px}

/* ─── License ─── */
.license-bar{
  margin-top:8px;
  padding:20px 0;text-align:center;
  font-size:13.5px;color:var(--text-muted);
}
.license-bar a{color:var(--text-secondary);text-decoration:underline;text-underline-offset:3px}

/* ─── Footer ─── */
.footer{
  padding:40px 0 48px;text-align:center;
  border-top:1px solid var(--border);
  margin-top:40px;
}
.footer p{font-size:13px;color:var(--text-muted)}
.footer a{color:var(--accent);text-decoration:none}

/* ─── Animations ─── */
@keyframes fadeUp{
  from{opacity:0;transform:translateY(16px)}
  to{opacity:1;transform:translateY(0)}
}
.anim{opacity:0;transform:translateY(20px);transition:opacity .5s,transform .5s}
.anim.visible{opacity:1;transform:translateY(0)}

/* ─── Responsive ─── */
@media(max-width:768px){
  .feature-grid{grid-template-columns:1fr}
  .results-grid{grid-template-columns:1fr}
  .server-card{flex-direction:column;text-align:center}
  .hero{padding:48px 0 40px}
  .section{padding:40px 0}
}
@media(max-width:480px){
  .badges{gap:6px}
  .badge{font-size:11px}
}
</style>
</head>
<body>

<!-- ═══════════════ HERO ═══════════════ -->
<header class="hero">
  <div class="hero-glow"></div>
  <div class="container" style="position:relative">

    <div class="hero-label">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
      GEOMETRY-ENHANCED PROTEIN LANGUAGE MODEL
    </div>

    <h1>Geo<span>ARG</span></h1>

    <p class="hero-subtitle">
      Discover novel antibiotic resistance genes that sequence-homology tools miss —
      powered by 3D catalytic-site geometry and knowledge distillation.
    </p>

    <!-- Badges Row -->
    <div class="badges">
      <span class="badge">
        <span class="badge-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg>Accuracy</span>
        <span class="badge-value green">98.92%</span>
      </span>
      <span class="badge">
        <span class="badge-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>Speedup</span>
        <span class="badge-value amber">15.4×</span>
      </span>
      <span class="badge">
        <span class="badge-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>Backbone</span>
        <span class="badge-value blue">ESM2</span>
      </span>
      <span class="badge">
        <span class="badge-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>License</span>
        <span class="badge-value purple">MIT</span>
      </span>
      <span class="badge">
        <span class="badge-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 002 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0022 16z"/></svg>Params</span>
        <span class="badge-value cyan">33.5M</span>
      </span>
      <span class="badge">
        <span class="badge-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>Python</span>
        <span class="badge-value rose">≥ 3.10</span>
      </span>
    </div>

    <!-- Callout -->
    <div class="callout">
      Sequence-homology tools miss ARGs that have diverged beyond recognition.
      <strong>GeoARG</strong> closes this gap by distilling 3D structural knowledge into a lightweight sequence-only model.
      <a href="https://github.com/XingqiaoLin/GeoARG">View on GitHub →</a>
    </div>

  </div>
</header>

<div class="divider"></div>

<main class="container">

<!-- ═══════════════ WHY ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon green">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
    </div>
    <h2 class="section-title">Why GeoARG?</h2>
  </div>
  <div class="feature-grid">
    <div class="feature-card">
      <div class="feature-card-icon" style="background:rgba(110,231,183,0.1)">🧬</div>
      <h3>All Input Types</h3>
      <p>Handles long/short nucleotide and amino acid sequences in a single unified model — no separate pipelines needed.</p>
    </div>
    <div class="feature-card">
      <div class="feature-card-icon" style="background:rgba(96,165,250,0.1)">🔬</div>
      <h3>Remote Homologs</h3>
      <p>Detects resistance genes down to &lt;25% sequence identity — far beyond what BLAST or HMM-based tools can find.</p>
    </div>
    <div class="feature-card">
      <div class="feature-card-icon" style="background:rgba(251,191,36,0.1)">⚡</div>
      <h3>15.4× Faster</h3>
      <p>Student model runs inference 15.4× faster than the full structural teacher with no measurable performance loss.</p>
    </div>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ ARCHITECTURE ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon blue">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/></svg>
    </div>
    <h2 class="section-title">Architecture</h2>
  </div>
  <div class="prose">
    <p>GeoARG follows a <strong>teacher–student</strong> design with three coordinated modules. The teacher combines a large protein language model with a geometry-aware graph encoder; the student inherits structural knowledge through distillation.</p>
  </div>
  <div class="arch-box">
    <table class="arch-table">
      <thead><tr><th>Module</th><th>Role</th></tr></thead>
      <tbody>
        <tr>
          <td>ESM2-650M + E(3)-GNN</td>
          <td>Extract sequence embeddings and residue-level structural geometry from predicted PDB structures</td>
        </tr>
        <tr>
          <td>Cross-Attention Fusion</td>
          <td>Fuse sequence and structure via cross-attention — queries from sequence, keys/values from structure</td>
        </tr>
        <tr>
          <td>Knowledge Distillation</td>
          <td>Transfer teacher's structural knowledge to lightweight ESM2-35M student at both logit and embedding levels</td>
        </tr>
      </tbody>
    </table>
    <div class="formula-block">
      <span class="label">Distillation objective:</span><br><br>
      <span class="math">ℒ = λ₁ · KL(y_teacher ∥ y_student) + λ₂ · (1/d)·‖z_teacher − z_student‖² + CE(y_true, y_student)</span><br><br>
      <span style="color:var(--text-muted);font-size:12px">At inference, <strong style="color:var(--accent)">only the student</strong> is used — no structure required.</span>
    </div>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ RESULTS ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon purple">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
    </div>
    <h2 class="section-title">Results</h2>
  </div>

  <div class="results-grid">
    <!-- ARG Identification -->
    <div class="result-panel">
      <h3><span class="dot" style="background:var(--accent)"></span>ARG Identification (UniProt)</h3>
      <table>
        <thead><tr><th>Method</th><th>Acc</th><th>MCC</th><th>AUROC</th></tr></thead>
        <tbody>
          <tr class="highlight"><td>GeoARG</td><td>0.9892</td><td>0.9684</td><td>0.9999</td></tr>
          <tr><td>ARGNet</td><td>0.9639</td><td>0.9076</td><td>0.9975</td></tr>
          <tr><td>HMD-ARG</td><td>0.9521</td><td>0.9101</td><td>0.9597</td></tr>
          <tr><td>DeepARG</td><td>0.9418</td><td>0.9041</td><td>0.9618</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Remote Homolog -->
    <div class="result-panel">
      <h3><span class="dot" style="background:var(--blue)"></span>Remote Homolog (0–40% ID)</h3>
      <table>
        <thead><tr><th>Method</th><th style="text-align:right">Recall</th></tr></thead>
        <tbody>
          <tr class="highlight"><td>GeoARG</td><td style="text-align:right">0.48</td></tr>
          <tr><td>HMD-ARG</td><td style="text-align:right">0.11</td></tr>
          <tr><td>ARGNet</td><td style="text-align:right">0.02</td></tr>
        </tbody>
      </table>
      <div style="margin-top:16px;padding:12px;border-radius:8px;background:var(--surface2);text-align:center">
        <span style="font-family:var(--mono);font-size:28px;font-weight:700;color:var(--accent)">24×</span>
        <p style="font-size:12px;color:var(--text-muted);margin-top:4px">better recall than ARGNet</p>
      </div>
    </div>

    <!-- Inference Efficiency -->
    <div class="result-panel result-full">
      <h3><span class="dot" style="background:var(--amber)"></span>Inference Efficiency</h3>
      <table>
        <thead><tr><th>Model</th><th>Parameters</th><th>Time (s)</th><th>Speedup</th></tr></thead>
        <tbody>
          <tr><td>Teacher (ESM2-650M + E(3)-GNN)</td><td>663.8M</td><td>1,709</td><td>1×</td></tr>
          <tr class="highlight"><td>Student (ESM2-35M)</td><td>33.5M</td><td>111</td><td>15.4×</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ INSTALLATION ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon amber">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    </div>
    <h2 class="section-title">Installation</h2>
  </div>

  <div class="code-block">
    <div class="code-header">
      <div class="code-dots"><span></span><span></span><span></span></div>
      <span class="code-lang">bash</span>
    </div>
    <div class="code-body"><span class="cmd">git clone</span> https://github.com/XingqiaoLin/GeoARG
<span class="cmd">cd</span> GeoARG

<span class="comment"># Create conda environment</span>
<span class="cmd">conda create</span> <span class="flag">-n</span> geoarg python=3.10 <span class="flag">-y</span>
<span class="cmd">conda activate</span> geoarg

<span class="comment"># Install dependencies</span>
<span class="cmd">pip install</span> torch torchvision <span class="flag">--index-url</span> <span class="str">https://download.pytorch.org/whl/cu118</span>
<span class="cmd">pip install</span> fair-esm biopython safetensors tqdm scikit-learn</div>
  </div>

  <div style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px">
    <span class="badge"><span class="badge-label">Python</span><span class="badge-value green">≥ 3.10</span></span>
    <span class="badge"><span class="badge-label">PyTorch</span><span class="badge-value blue">≥ 2.0</span></span>
    <span class="badge"><span class="badge-label">CUDA</span><span class="badge-value amber">11.8+</span></span>
    <span class="badge"><span class="badge-label">VRAM (teacher)</span><span class="badge-value rose">24 GB</span></span>
    <span class="badge"><span class="badge-label">VRAM (student)</span><span class="badge-value cyan">8 GB</span></span>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ USAGE ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon cyan">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
    </div>
    <h2 class="section-title">Usage</h2>
  </div>

  <h3 style="font-size:17px;font-weight:700;color:#fff;margin-bottom:14px;display:flex;align-items:center;gap:8px">
    <span style="color:var(--accent)">▸</span> Inference
  </h3>

  <div class="code-block">
    <div class="code-header">
      <div class="code-dots"><span></span><span></span><span></span></div>
      <span class="code-lang">bash</span>
    </div>
    <div class="code-body"><span class="cmd">python</span> infer.py \
    <span class="flag">--fasta</span> <span class="str">sequences.fasta</span> \
    <span class="flag">--base_model</span> <span class="str">/path/to/checkpoints/merged_model</span> \
    <span class="flag">--out_csv</span> <span class="str">predictions.csv</span> \
    <span class="flag">--local_files_only</span></div>
  </div>

  <table class="arg-table">
    <thead><tr><th>Argument</th><th>Default</th><th>Description</th></tr></thead>
    <tbody>
      <tr><td>--fasta</td><td>—</td><td>Input protein FASTA file(s)</td></tr>
      <tr><td>--base_model</td><td>esm2_t12_35M</td><td>HuggingFace model name or local checkpoint</td></tr>
      <tr><td>--out_csv</td><td>—</td><td>Output CSV path</td></tr>
      <tr><td>--thr</td><td>0.5</td><td>Decision threshold on predicted probability</td></tr>
      <tr><td>--batch_size</td><td>4</td><td>Sequences per batch</td></tr>
      <tr><td>--max_length</td><td>1022</td><td>Tokenizer max length (ESM2 standard)</td></tr>
      <tr><td>--dtype</td><td>float32</td><td>Model dtype: float32 / float16 / bfloat16</td></tr>
      <tr><td>--device</td><td>auto</td><td>cuda or cpu</td></tr>
    </tbody>
  </table>

  <p style="margin-top:16px;font-size:13.5px;color:var(--text-muted)">
    Output CSV columns: <code style="background:var(--surface2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px;color:var(--text-secondary)">seq_id</code>,
    <code style="background:var(--surface2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px;color:var(--text-secondary)">prob</code>,
    <code style="background:var(--surface2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px;color:var(--text-secondary)">pred</code>
  </p>

  <h3 style="font-size:17px;font-weight:700;color:#fff;margin:32px 0 14px;display:flex;align-items:center;gap:8px">
    <span style="color:var(--blue)">▸</span> Training
  </h3>

  <div class="code-block">
    <div class="code-header">
      <div class="code-dots"><span></span><span></span><span></span></div>
      <span class="code-lang">bash</span>
    </div>
    <div class="code-body"><span class="cmd">python</span> train.py</div>
  </div>

  <div class="prose" style="margin-top:16px">
    <p>Training runs <strong>two phases automatically</strong>: Phase 1 trains the teacher (ESM2-650M backbone with last 4 layers unfrozen + E3-GNN + CrossAttention). Phase 2 distills into the student (ESM2-35M) with the teacher frozen.</p>
  </div>

  <h3 style="font-size:17px;font-weight:700;color:#fff;margin:32px 0 14px;display:flex;align-items:center;gap:8px">
    <span style="color:var(--purple)">▸</span> Predict Structures with ESMFold
  </h3>

  <div class="code-block">
    <div class="code-header">
      <div class="code-dots"><span></span><span></span><span></span></div>
      <span class="code-lang">bash</span>
    </div>
    <div class="code-body"><span class="cmd">python</span> <span class="flag">-m</span> esm.scripts.fold <span class="flag">-i</span> <span class="str">sequences.fasta</span> <span class="flag">-o</span> <span class="str">pdbs/</span> <span class="flag">--tqdm</span></div>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ DATA FORMAT ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon rose">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="M9 15h6"/></svg>
    </div>
    <h2 class="section-title">Data Format</h2>
  </div>

  <div class="results-grid">
    <div class="result-panel">
      <h3><span class="dot" style="background:var(--rose)"></span>CSV (one row per protein)</h3>
      <table>
        <thead><tr><th>header</th><th>sequence</th><th>label1</th></tr></thead>
        <tbody>
          <tr><td>protein_001</td><td style="color:var(--text-muted);font-size:12px">MKKFTREDW...</td><td>1</td></tr>
          <tr><td>protein_002</td><td style="color:var(--text-muted);font-size:12px">MVHLTPEEK...</td><td>0</td></tr>
        </tbody>
      </table>
    </div>
    <div class="result-panel">
      <h3><span class="dot" style="background:var(--amber)"></span>PDB Directory</h3>
      <p style="font-size:13.5px;color:var(--text-secondary);line-height:1.6;padding:12px 0">
        One <code style="background:var(--surface2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px">.pdb</code> file per sequence, named <code style="background:var(--surface2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:12px">{header}.pdb</code>
      </p>
    </div>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ REPO STRUCTURE ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon green">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>
    </div>
    <h2 class="section-title">Repository Structure</h2>
  </div>

  <div class="tree">
<span class="folder">GeoARG/</span>
├── <span class="file">models.py</span>       <span class="desc"># Teacher, Student, E3GNN, CrossAttention, DistillationLoss</span>
├── <span class="file">train.py</span>        <span class="desc"># Two-phase training entry point</span>
├── <span class="file">trainer.py</span>      <span class="desc"># Epoch-level train / eval loops</span>
├── <span class="file">data.py</span>         <span class="desc"># Dataset, PDB→graph parser, collate_fn</span>
├── <span class="file">utils.py</span>        <span class="desc"># Metrics, seed, sequence utilities</span>
├── <span class="file">workflow.png</span>    <span class="desc"># Architecture figure</span>
└── <span class="folder">checkpoints/</span>    <span class="desc"># Saved model weights (.safetensors)</span>
  </div>
</section>

<div class="divider"></div>

<!-- ═══════════════ WEB SERVER ═══════════════ -->
<section class="section anim">
  <div class="section-header">
    <div class="section-icon blue">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
    </div>
    <h2 class="section-title">Web Server</h2>
  </div>

  <div class="server-card">
    <div class="server-card-icon">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 10h-1.26A8 8 0 109 20h9a5 5 0 000-10z"/></svg>
    </div>
    <div>
      <h3>Online Prediction Server</h3>
      <p>Single-sequence or batch prediction without local setup. Accepts FASTA input and returns ARG probability, predicted resistance class, and confidence score.</p>
      <a class="btn" href="https://ycclab.cuhk.edu.cn/GeoARG/" target="_blank">
        Launch Web Server
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
    </div>
  </div>
</section>

<!-- ═══════════════ LICENSE ═══════════════ -->
<div class="divider"></div>
<div class="license-bar container">
  This project is licensed under the <a href="#">MIT License</a> — see the LICENSE file for details.
</div>

<!-- ═══════════════ FOOTER ═══════════════ -->
<footer class="footer">
  <div class="container">
    <p>GeoARG · <a href="https://github.com/XingqiaoLin/GeoARG">GitHub</a> · Geometry-Enhanced Protein Language Modeling</p>
  </div>
</footer>

</main>

<script>
// Intersection Observer for scroll animations
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
    }
  });
}, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.anim').forEach(el => observer.observe(el));
</script>
</body>
</html>

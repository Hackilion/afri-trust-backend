/**
 * AfriTrust Web SDK v1.0
 *
 * Embeddable identity verification flow. Zero dependencies, framework-agnostic.
 *
 * Usage:
 *   <script src="https://your-api.com/sdk/afritrust.js"></script>
 *   <div id="kyc-container"></div>
 *   <script>
 *     AfriTrust.start({
 *       apiKey: "your-api-key",
 *       containerId: "kyc-container",
 *       workflowId: "uuid",
 *       applicant: { external_id: "u1", email: "a@b.com", full_name: "Name" },
 *       onComplete: (r) => console.log(r),
 *       onError: (e) => console.error(e),
 *     });
 *   </script>
 */
(function (global) {
  "use strict";

  const VERSION = "1.0.0";

  /* ------------------------------------------------------------------ */
  /*  CSS – injected into Shadow DOM for full isolation                  */
  /* ------------------------------------------------------------------ */
  const STYLES = `
    :host { display:block; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:#1a1a2e; }
    * { box-sizing:border-box; margin:0; padding:0; }

    .at-root { max-width:520px; margin:0 auto; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; background:#fff; box-shadow:0 4px 24px rgba(0,0,0,.08); }

    /* Header */
    .at-header { background:linear-gradient(135deg,#0f3460,#16213e); color:#fff; padding:20px 24px; }
    .at-header h2 { font-size:18px; font-weight:600; margin-bottom:4px; }
    .at-header p  { font-size:13px; opacity:.8; }

    /* Progress */
    .at-progress { display:flex; padding:16px 24px; gap:8px; background:#f8fafc; border-bottom:1px solid #e2e8f0; }
    .at-step-dot { flex:1; height:6px; border-radius:3px; background:#e2e8f0; transition:background .3s; }
    .at-step-dot.done { background:#10b981; }
    .at-step-dot.active { background:#3b82f6; }
    .at-step-label { font-size:12px; color:#64748b; padding:0 24px 12px; background:#f8fafc; }

    /* Body */
    .at-body { padding:24px; }

    /* Form */
    .at-field { margin-bottom:16px; }
    .at-field label { display:block; font-size:13px; font-weight:500; color:#374151; margin-bottom:5px; }
    .at-field label .req { color:#ef4444; }
    .at-field input, .at-field select { width:100%; padding:10px 12px; border:1px solid #d1d5db; border-radius:8px; font-size:14px; outline:none; transition:border .2s; }
    .at-field input:focus, .at-field select:focus { border-color:#3b82f6; box-shadow:0 0 0 3px rgba(59,130,246,.15); }
    .at-field .at-hint { font-size:11px; color:#9ca3af; margin-top:3px; }
    .at-field .at-err  { font-size:11px; color:#ef4444; margin-top:3px; }
    .at-field input.invalid { border-color:#ef4444; }

    /* Buttons */
    .at-btn { display:inline-flex; align-items:center; justify-content:center; gap:8px; width:100%; padding:12px; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; transition:background .2s,opacity .2s; }
    .at-btn-primary { background:#3b82f6; color:#fff; }
    .at-btn-primary:hover { background:#2563eb; }
    .at-btn-primary:disabled { opacity:.5; cursor:not-allowed; }
    .at-btn-secondary { background:#f1f5f9; color:#374151; margin-top:8px; }
    .at-btn-success { background:#10b981; color:#fff; }

    /* Doc cards */
    .at-doc-types { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px; }
    .at-doc-card { padding:14px; border:2px solid #e2e8f0; border-radius:10px; text-align:center; cursor:pointer; transition:border .2s,background .2s; font-size:13px; font-weight:500; }
    .at-doc-card:hover { border-color:#93c5fd; background:#eff6ff; }
    .at-doc-card.selected { border-color:#3b82f6; background:#dbeafe; }

    /* File upload area */
    .at-upload { border:2px dashed #d1d5db; border-radius:10px; padding:32px 16px; text-align:center; cursor:pointer; transition:border .2s; margin-bottom:16px; }
    .at-upload:hover { border-color:#3b82f6; }
    .at-upload.has-file { border-style:solid; border-color:#10b981; background:#f0fdf4; }
    .at-upload p { font-size:13px; color:#6b7280; }
    .at-upload .filename { font-size:12px; color:#10b981; font-weight:600; margin-top:6px; }
    .at-upload input[type=file] { display:none; }

    /* Camera */
    .at-camera { text-align:center; }
    .at-camera video { width:100%; max-width:360px; border-radius:10px; border:2px solid #e2e8f0; margin-bottom:12px; }
    .at-camera canvas { display:none; }
    .at-camera .preview { display:block; max-width:360px; margin:0 auto 12px; border-radius:10px; border:2px solid #10b981; }

    /* Status */
    .at-status { text-align:center; padding:40px 16px; }
    .at-status .icon { font-size:56px; margin-bottom:12px; }
    .at-status h3 { font-size:20px; margin-bottom:8px; }
    .at-status p  { font-size:14px; color:#6b7280; }

    /* Loading */
    .at-loading { display:flex; align-items:center; justify-content:center; padding:48px; }
    .at-spinner { width:32px; height:32px; border:3px solid #e2e8f0; border-top-color:#3b82f6; border-radius:50%; animation:spin .7s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }

    /* Alert */
    .at-alert { padding:10px 14px; border-radius:8px; font-size:13px; margin-bottom:16px; }
    .at-alert-error { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
    .at-alert-info  { background:#eff6ff; color:#1e40af; border:1px solid #bfdbfe; }
  `;

  /* ------------------------------------------------------------------ */
  /*  API Client                                                        */
  /* ------------------------------------------------------------------ */
  class ApiClient {
    constructor(baseUrl, apiKey) {
      this.baseUrl = baseUrl.replace(/\/+$/, "");
      this.headers = { "X-API-Key": apiKey };
    }

    async _req(method, path, body, isFormData) {
      const opts = { method, headers: { ...this.headers } };
      if (body && !isFormData) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      } else if (body && isFormData) {
        opts.body = body;
      }
      const res = await fetch(this.baseUrl + path, opts);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw { status: res.status, detail: data.detail || res.statusText, data };
      return data;
    }

    createApplicant(info)          { return this._req("POST", "/v1/applicants", info); }
    startSession(applicantId, wfId){ return this._req("POST", "/v1/verifications", { applicant_id: applicantId, workflow_id: wfId }); }
    getRequiredData(sessionId)     { return this._req("GET",  `/v1/verifications/${sessionId}/required-data`); }
    getSession(sessionId)          { return this._req("GET",  `/v1/verifications/${sessionId}`); }
    submitAttributes(sessionId, a) { return this._req("POST", `/v1/verifications/${sessionId}/attributes`, { attributes: a }); }

    uploadDocument(sessionId, type, file) {
      const fd = new FormData();
      fd.append("document_type", type);
      fd.append("file", file);
      return this._req("POST", `/v1/verifications/${sessionId}/documents`, fd, true);
    }

    uploadSelfie(sessionId, blob) {
      const fd = new FormData();
      fd.append("file", blob, "selfie.jpg");
      return this._req("POST", `/v1/verifications/${sessionId}/selfie`, fd, true);
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Renderer                                                          */
  /* ------------------------------------------------------------------ */
  const DOC_LABELS = {
    passport: "Passport", national_id: "National ID", drivers_license: "Driver's License",
    voter_card: "Voter Card", residence_permit: "Residence Permit", address_proof: "Address Proof", other: "Other",
  };

  class Renderer {
    constructor(shadowRoot) { this.root = shadowRoot; }

    loading() {
      this.root.querySelector(".at-body").innerHTML = `<div class="at-loading"><div class="at-spinner"></div></div>`;
    }

    error(msg) {
      return `<div class="at-alert at-alert-error">${this._esc(msg)}</div>`;
    }

    _esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

    renderProgress(current, total, tierName) {
      let dots = "";
      for (let i = 1; i <= total; i++) {
        const cls = i < current ? "done" : i === current ? "active" : "";
        dots += `<div class="at-step-dot ${cls}"></div>`;
      }
      this.root.querySelector(".at-progress").innerHTML = dots;
      this.root.querySelector(".at-step-label").textContent = `Step ${current} of ${total} — ${tierName || ""}`;
    }

    renderAttributeForm(schema, collected, onSubmit) {
      const missing = schema.filter(a => !collected.includes(a.key));
      if (missing.length === 0) return;

      let html = `<h3 style="font-size:15px;margin-bottom:14px;color:#1e293b;">Fill in your details</h3>`;
      for (const attr of missing) {
        const req = attr.required ? `<span class="req">*</span>` : "";
        const desc = attr.description ? `<div class="at-hint">${this._esc(attr.description)}</div>` : "";
        let input = "";

        if (attr.data_type === "enum" && attr.options) {
          const opts = attr.options.map(o => `<option value="${this._esc(o)}">${this._esc(o)}</option>`).join("");
          input = `<select name="${attr.key}"><option value="">Select...</option>${opts}</select>`;
        } else if (attr.data_type === "date") {
          input = `<input type="date" name="${attr.key}"${attr.required ? " required" : ""}>`;
        } else if (attr.data_type === "number") {
          const min = attr.validation?.min != null ? ` min="${attr.validation.min}"` : "";
          const max = attr.validation?.max != null ? ` max="${attr.validation.max}"` : "";
          input = `<input type="number" name="${attr.key}"${min}${max}${attr.required ? " required" : ""}>`;
        } else if (attr.data_type === "boolean") {
          input = `<label style="display:flex;align-items:center;gap:8px;font-size:14px;"><input type="checkbox" name="${attr.key}" style="width:auto;"> ${this._esc(attr.label)}</label>`;
        } else {
          const ml = attr.validation?.min_length ? ` minlength="${attr.validation.min_length}"` : "";
          const xl = attr.validation?.max_length ? ` maxlength="${attr.validation.max_length}"` : "";
          const pat = attr.validation?.pattern ? ` pattern="${this._esc(attr.validation.pattern)}"` : "";
          input = `<input type="text" name="${attr.key}" placeholder="${this._esc(attr.label)}"${ml}${xl}${pat}${attr.required ? " required" : ""}>`;
        }

        html += `<div class="at-field"><label>${this._esc(attr.label)} ${req}</label>${attr.data_type !== "boolean" ? input : ""}${attr.data_type === "boolean" ? input : ""}${desc}</div>`;
      }
      html += `<div id="at-form-err"></div>`;
      html += `<button class="at-btn at-btn-primary" id="at-submit-attrs">Continue</button>`;

      const body = this.root.querySelector(".at-body");
      body.innerHTML = html;

      body.querySelector("#at-submit-attrs").addEventListener("click", () => {
        const values = {};
        let valid = true;
        for (const attr of missing) {
          const el = body.querySelector(`[name="${attr.key}"]`);
          if (!el) continue;
          let val = attr.data_type === "boolean" ? el.checked : el.value.trim();
          if (attr.data_type === "number" && val !== "") val = parseFloat(val);

          if (attr.required && (val === "" || val === null || val === undefined)) {
            el.classList.add("invalid");
            valid = false;
          } else {
            el.classList.remove("invalid");
            if (val !== "" && val !== false) values[attr.key] = val;
          }
        }
        if (!valid) {
          body.querySelector("#at-form-err").innerHTML = this.error("Please fill in all required fields.");
          return;
        }
        body.querySelector("#at-submit-attrs").disabled = true;
        body.querySelector("#at-submit-attrs").textContent = "Submitting...";
        onSubmit(values);
      });
    }

    renderDocumentUpload(acceptedTypes, onUpload) {
      let html = `<h3 style="font-size:15px;margin-bottom:14px;color:#1e293b;">Upload your identity document</h3>`;
      html += `<div class="at-doc-types">`;
      for (const t of acceptedTypes) {
        html += `<div class="at-doc-card" data-type="${t}">${DOC_LABELS[t] || t}</div>`;
      }
      html += `</div>`;
      html += `<div class="at-upload" id="at-drop-zone"><p>Click or drag to upload document</p><input type="file" accept="image/*,.pdf" id="at-doc-file"></div>`;
      html += `<div id="at-doc-err"></div>`;
      html += `<button class="at-btn at-btn-primary" id="at-upload-doc" disabled>Upload Document</button>`;

      const body = this.root.querySelector(".at-body");
      body.innerHTML = html;

      let selectedType = null;
      let selectedFile = null;

      body.querySelectorAll(".at-doc-card").forEach(card => {
        card.addEventListener("click", () => {
          body.querySelectorAll(".at-doc-card").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");
          selectedType = card.dataset.type;
          body.querySelector("#at-upload-doc").disabled = !(selectedType && selectedFile);
        });
      });

      const dropZone = body.querySelector("#at-drop-zone");
      const fileInput = body.querySelector("#at-doc-file");

      dropZone.addEventListener("click", () => fileInput.click());
      dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.style.borderColor = "#3b82f6"; });
      dropZone.addEventListener("dragleave", () => { dropZone.style.borderColor = ""; });
      dropZone.addEventListener("drop", e => {
        e.preventDefault(); dropZone.style.borderColor = "";
        if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
      });

      fileInput.addEventListener("change", () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

      const handleFile = (file) => {
        selectedFile = file;
        dropZone.classList.add("has-file");
        dropZone.innerHTML = `<p>Selected</p><div class="filename">${this._esc(file.name)} (${(file.size / 1024).toFixed(0)} KB)</div>`;
        body.querySelector("#at-upload-doc").disabled = !selectedType;
      };

      body.querySelector("#at-upload-doc").addEventListener("click", () => {
        if (!selectedType || !selectedFile) return;
        body.querySelector("#at-upload-doc").disabled = true;
        body.querySelector("#at-upload-doc").textContent = "Uploading...";
        onUpload(selectedType, selectedFile);
      });
    }

    renderSelfieCapture(label, onCapture) {
      let html = `<h3 style="font-size:15px;margin-bottom:14px;color:#1e293b;">${this._esc(label)}</h3>`;
      html += `<div class="at-camera">
        <video id="at-video" autoplay playsinline></video>
        <canvas id="at-canvas"></canvas>
        <img id="at-preview" class="preview" style="display:none;">
        <button class="at-btn at-btn-primary" id="at-capture">Capture Photo</button>
        <button class="at-btn at-btn-secondary" id="at-retake" style="display:none;">Retake</button>
        <button class="at-btn at-btn-success" id="at-confirm" style="display:none;">Use This Photo</button>
        <div style="margin-top:12px;"><button class="at-btn at-btn-secondary" id="at-file-fallback">Upload from device instead</button></div>
        <input type="file" accept="image/*" capture="user" id="at-selfie-file" style="display:none;">
      </div>`;
      html += `<div id="at-selfie-err" style="margin-top:8px;"></div>`;

      const body = this.root.querySelector(".at-body");
      body.innerHTML = html;

      const video = body.querySelector("#at-video");
      const canvas = body.querySelector("#at-canvas");
      const preview = body.querySelector("#at-preview");
      const captureBtn = body.querySelector("#at-capture");
      const retakeBtn = body.querySelector("#at-retake");
      const confirmBtn = body.querySelector("#at-confirm");
      const fallbackBtn = body.querySelector("#at-file-fallback");
      const fileInput = body.querySelector("#at-selfie-file");
      let stream = null;
      let capturedBlob = null;

      const startCamera = async () => {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } } });
          video.srcObject = stream;
          video.style.display = "block";
          captureBtn.style.display = "";
        } catch {
          video.style.display = "none";
          captureBtn.style.display = "none";
          fallbackBtn.textContent = "Select photo from device";
        }
      };
      startCamera();

      captureBtn.addEventListener("click", () => {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        canvas.toBlob(blob => {
          capturedBlob = blob;
          preview.src = URL.createObjectURL(blob);
          preview.style.display = "block";
          video.style.display = "none";
          captureBtn.style.display = "none";
          retakeBtn.style.display = "";
          confirmBtn.style.display = "";
        }, "image/jpeg", 0.85);
      });

      retakeBtn.addEventListener("click", () => {
        preview.style.display = "none";
        video.style.display = "block";
        captureBtn.style.display = "";
        retakeBtn.style.display = "none";
        confirmBtn.style.display = "none";
        capturedBlob = null;
      });

      confirmBtn.addEventListener("click", () => {
        if (!capturedBlob) return;
        confirmBtn.disabled = true;
        confirmBtn.textContent = "Uploading...";
        if (stream) stream.getTracks().forEach(t => t.stop());
        onCapture(capturedBlob);
      });

      fallbackBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", () => {
        const file = fileInput.files[0];
        if (!file) return;
        if (stream) stream.getTracks().forEach(t => t.stop());
        video.style.display = "none";
        captureBtn.style.display = "none";
        preview.src = URL.createObjectURL(file);
        preview.style.display = "block";
        confirmBtn.style.display = "";
        confirmBtn.addEventListener("click", () => {
          confirmBtn.disabled = true;
          confirmBtn.textContent = "Uploading...";
          onCapture(file);
        }, { once: true });
      });
    }

    renderResult(result, details) {
      const icons = { approved: "\u2705", rejected: "\u274C", pending: "\u23F3" };
      const titles = { approved: "Verification Approved", rejected: "Verification Not Approved", pending: "Verification Pending" };
      const msgs = {
        approved: "Your identity has been successfully verified.",
        rejected: "We were unable to verify your identity. Please contact support.",
        pending: "Your verification is being reviewed. You will be notified of the result."
      };
      const body = this.root.querySelector(".at-body");
      body.innerHTML = `
        <div class="at-status">
          <div class="icon">${icons[result] || "\u2753"}</div>
          <h3>${titles[result] || result}</h3>
          <p>${msgs[result] || ""}</p>
          ${details ? `<p style="margin-top:12px;font-size:12px;color:#9ca3af;">${this._esc(JSON.stringify(details))}</p>` : ""}
        </div>`;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  SDK Controller                                                    */
  /* ------------------------------------------------------------------ */
  class AfriTrustSDK {
    constructor(config) {
      this.config = config;
      this.api = new ApiClient(config.baseUrl || window.location.origin, config.apiKey);
      this.sessionId = null;
      this.totalSteps = 0;
      this.currentPhase = null;
    }

    async start() {
      const container = document.getElementById(this.config.containerId);
      if (!container) throw new Error(`Container #${this.config.containerId} not found`);

      const shadow = container.attachShadow({ mode: "open" });
      shadow.innerHTML = `<style>${STYLES}</style>
        <div class="at-root">
          <div class="at-header"><h2>Identity Verification</h2><p>Powered by AfriTrust</p></div>
          <div class="at-progress"></div>
          <div class="at-step-label"></div>
          <div class="at-body"><div class="at-loading"><div class="at-spinner"></div></div></div>
        </div>`;
      this.renderer = new Renderer(shadow);

      try {
        const applicant = await this.api.createApplicant(this.config.applicant || {});
        const session = await this.api.startSession(applicant.id, this.config.workflowId);
        this.sessionId = session.id;
        this._cb("onStepChange", { event: "session_created", sessionId: session.id });
        await this._processStep();
      } catch (err) {
        if (err.status === 400 && err.detail?.includes("active verification session")) {
          try {
            const applicant = await this.api.createApplicant(this.config.applicant || {});
            const sessions = await this.api._req("GET", `/v1/verifications?applicant_id=${applicant.id}&page_size=1`);
            if (sessions.items && sessions.items.length > 0) {
              this.sessionId = sessions.items[0].id;
              await this._processStep();
              return;
            }
          } catch {}
        }
        this.renderer.renderResult("pending", null);
        const body = this.renderer.root.querySelector(".at-body");
        body.innerHTML = this.renderer.error(err.detail || "Failed to start verification") + body.innerHTML;
        this._cb("onError", err);
      }
    }

    async _processStep() {
      this.renderer.loading();

      try {
        const rd = await this.api.getRequiredData(this.sessionId);

        if (rd.complete) {
          const session = await this.api.getSession(this.sessionId);
          this.renderer.renderProgress(session.current_step_order, session.current_step_order, "Complete");
          this.renderer.renderResult(session.result, session.result_details);
          this._cb("onComplete", { result: session.result, sessionId: this.sessionId, details: session.result_details });
          return;
        }

        const session = await this.api.getSession(this.sessionId);
        this.totalSteps = session.steps ? session.steps.length : rd.current_step_order;
        this.renderer.renderProgress(rd.current_step_order, this.totalSteps, rd.tier_profile_name);
        this._cb("onStepChange", { step: rd.current_step_order, tier: rd.tier_profile_name });

        if (session.status === "approved" || session.status === "rejected") {
          this.renderer.renderResult(session.result, session.result_details);
          this._cb("onComplete", { result: session.result, sessionId: this.sessionId });
          return;
        }

        const missingAttrs = rd.attributes.missing_required || [];
        const pendingChecks = rd.checks.pending || [];
        const acceptedDocs = rd.accepted_document_types || [];
        const schema = rd.attributes.schema || [];

        if (missingAttrs.length > 0) {
          this.currentPhase = "attributes";
          this.renderer.renderAttributeForm(schema, rd.attributes.collected, async (values) => {
            try {
              await this.api.submitAttributes(this.sessionId, values);
              await this._processStep();
            } catch (err) {
              const body = this.renderer.root.querySelector(".at-body");
              const errDiv = body.querySelector("#at-form-err");
              if (errDiv) errDiv.innerHTML = this.renderer.error(err.detail || "Submission failed");
              const btn = body.querySelector("#at-submit-attrs");
              if (btn) { btn.disabled = false; btn.textContent = "Continue"; }
              this._cb("onError", err);
            }
          });
          return;
        }

        const needsDoc = pendingChecks.some(c => ["government_id", "address_proof"].includes(c));
        if (needsDoc && acceptedDocs.length > 0) {
          this.currentPhase = "document";
          this.renderer.renderDocumentUpload(acceptedDocs, async (type, file) => {
            try {
              await this.api.uploadDocument(this.sessionId, type, file);
              await this._processStep();
            } catch (err) {
              const body = this.renderer.root.querySelector(".at-body");
              const errDiv = body.querySelector("#at-doc-err");
              if (errDiv) errDiv.innerHTML = this.renderer.error(err.detail || "Upload failed");
              const btn = body.querySelector("#at-upload-doc");
              if (btn) { btn.disabled = false; btn.textContent = "Upload Document"; }
              this._cb("onError", err);
            }
          });
          return;
        }

        const needsSelfie = pendingChecks.some(c => ["selfie", "face_match", "liveness"].includes(c));
        if (needsSelfie) {
          this.currentPhase = "selfie";
          const label = pendingChecks.includes("face_match")
            ? "Take a selfie for face matching"
            : "Take a selfie for liveness verification";
          this.renderer.renderSelfieCapture(label, async (blob) => {
            try {
              await this.api.uploadSelfie(this.sessionId, blob);
              await this._processStep();
            } catch (err) {
              const body = this.renderer.root.querySelector(".at-body");
              const errDiv = body.querySelector("#at-selfie-err");
              if (errDiv) errDiv.innerHTML = this.renderer.error(err.detail || "Upload failed");
              this._cb("onError", err);
            }
          });
          return;
        }

        const finalSession = await this.api.getSession(this.sessionId);
        this.renderer.renderResult(finalSession.result, finalSession.result_details);
        this._cb("onComplete", { result: finalSession.result, sessionId: this.sessionId });

      } catch (err) {
        this.renderer.renderResult("pending", null);
        const body = this.renderer.root.querySelector(".at-body");
        body.innerHTML = this.renderer.error(err.detail || "An error occurred") + body.innerHTML;
        this._cb("onError", err);
      }
    }

    _cb(name, data) {
      if (typeof this.config[name] === "function") {
        try { this.config[name](data); } catch {}
      }
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Public API                                                        */
  /* ------------------------------------------------------------------ */
  global.AfriTrust = {
    version: VERSION,
    start(config) {
      if (!config.apiKey) throw new Error("AfriTrust: apiKey is required");
      if (!config.containerId) throw new Error("AfriTrust: containerId is required");
      if (!config.workflowId) throw new Error("AfriTrust: workflowId is required");
      const sdk = new AfriTrustSDK(config);
      sdk.start();
      return sdk;
    }
  };

})(typeof window !== "undefined" ? window : this);

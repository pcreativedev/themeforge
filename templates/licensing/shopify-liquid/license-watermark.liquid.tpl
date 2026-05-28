{% comment %}
  pcreative license-watermark — SIEMPRE se renderiza (no es opt-in).
  Si la licencia NO es válida, se muestra un sello "Theme: __PROJECT__
  · Unlicensed copy" en la esquina inferior. El watermark_id del JWT
  válido permite trazabilidad de filtrados (cada licencia tiene un id
  único embebido en el JWT).

  Pega esto en layout/theme.liquid justo antes de </body>:
    {%- render 'license-watermark' -%}
{% endcomment %}

<div id="pcreative-watermark"
     style="position:fixed;bottom:8px;right:8px;background:#fef3c7;color:#92400e;padding:6px 10px;border:1px solid #f59e0b;border-radius:6px;font:11px/1.2 system-ui;z-index:2147483647;display:none;"
     role="status"
     aria-live="polite">
  Theme: <strong>__PROJECT__</strong> · Unlicensed copy
</div>
<script>
  (function () {
    function maybeShow() {
      var s = window.pcreativeLicense && window.pcreativeLicense.state;
      var el = document.getElementById("pcreative-watermark");
      if (!el) return;
      // Show solo si el client ya intentó verificar y NO validó.
      if (s && s.ready && !s.valid) el.style.display = "block";
      else el.style.display = "none";
      // Watermark ID invisible (en data-attribute para grep cuando se filtre)
      if (s && s.valid && s.claims && s.claims.watermark) {
        el.setAttribute("data-pcre-w", s.claims.watermark);
      }
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { setTimeout(maybeShow, 500); });
    } else { setTimeout(maybeShow, 500); }
    // re-check después de heartbeat
    setInterval(maybeShow, 60 * 1000);
  })();
</script>

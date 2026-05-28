{% comment %}
  pcreative license-gate snippet — envuelve contenido premium que solo
  debe renderizar si la licencia es válida. Estrategia en 2 capas:

  1. Server-side (Liquid): si NO hay purchase_code en settings, ni siquiera
     renderizamos el contenido — devolvemos un placeholder con CTA al
     theme settings. Esto es lo que ve un nulled-user.
  2. Client-side (JS): si SÍ hay code pero el JWT no valida, el JS
     oculta el <div data-pcreative-gated="true"> al cargar.

  Combinado con la "license-watermark" que SIEMPRE renderiza el footer
  con un sello "Demo mode" si JS no marca valid, dificulta el theft
  cosmético.

  Uso desde una section:
    {%- render 'license-gate' with content -%}
      <h2>Premium section</h2>
      …
    {%- endrender -%}

  Alternativa más simple (sin nested capture):
    {%- if settings.purchase_code != blank -%}
      <div data-pcreative-gated="true">
        … contenido premium …
      </div>
    {%- else -%}
      {%- render 'license-gate-placeholder' -%}
    {%- endif -%}
{% endcomment %}

{%- if settings.purchase_code != blank -%}
  <div data-pcreative-gated="true" class="pcreative-gated">{{ content }}</div>
{%- else -%}
  <div class="pcreative-gate-placeholder" role="status" aria-live="polite">
    <p><strong>Premium section locked.</strong></p>
    <p>Add your purchase code at <code>Online Store → Themes → Customize → Theme settings → License</code>.</p>
  </div>
{%- endif -%}

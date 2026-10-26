/**
 * Browser-side mirror of the backend email renderer.
 *
 * It is used for instant canvas previews and for sending the current editor
 * state to the test-send endpoint.  The backend re-renders and sanitises the
 * saved HTML, so this module never becomes a security boundary by itself.
 */
import type {
  Branding,
  EmailButtonBlock,
  EmailDesign,
  EmailDesignBlock,
  EmailDividerBlock,
  EmailFooterBlock,
  EmailHtmlBlock,
  EmailImageBlock,
  EmailLogoBlock,
  EmailSpacerBlock,
  EmailTextBlock,
} from '@/types';
import { MERGE_TAGS } from './types';

const FONT_STACKS: Record<string, string> = {
  Cairo: "'Cairo','Tajawal','Segoe UI',Tahoma,Arial,sans-serif",
  Tajawal: "'Tajawal','Cairo','Segoe UI',Tahoma,Arial,sans-serif",
  'Segoe UI': "'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
  Tahoma: 'Tahoma,Arial,sans-serif',
  Arial: 'Arial,Helvetica,sans-serif',
  Helvetica: 'Helvetica,Arial,sans-serif',
  Georgia: "Georgia,'Times New Roman',serif",
  Verdana: 'Verdana,Geneva,sans-serif',
  'system-ui': "system-ui,-apple-system,'Segoe UI',sans-serif",
};

const MERGE_LABELS = Object.fromEntries(MERGE_TAGS.map((item) => [item.token, item.label]));

export interface RenderOptions {
  /** Translate merge tags to human-readable labels for the editor canvas. */
  forEditor?: boolean;
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function safeUrl(value: string): string {
  const raw = (value || '').trim();
  if (!raw) return '';
  const compact = raw.replace(/[\p{Cc}\s]+/gu, '').toLowerCase();
  if (raw.startsWith('{{') || raw.startsWith('[')) return raw;
  if (compact.startsWith('#')) return raw;
  if (
    compact.startsWith('http://') ||
    compact.startsWith('https://') ||
    compact.startsWith('mailto:') ||
    compact.startsWith('tel:') ||
    compact.startsWith('/') ||
    compact.startsWith('./') ||
    compact.startsWith('../')
  ) {
    return raw;
  }
  if (!/^[a-z][a-z0-9+.-]*:/i.test(compact)) return raw;
  return '';
}

function fontStack(design: EmailDesign): string {
  return FONT_STACKS[design.settings.font_family] || FONT_STACKS.Cairo;
}

function primary(branding?: Branding | null): string {
  return branding?.primary_color || '#0F6CBD';
}

function companyName(branding?: Branding | null): string {
  return branding?.company_name || 'شركتك';
}

function initial(branding?: Branding | null): string {
  const parts = companyName(branding).trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0] || ''}${parts[1][0] || ''}`.toUpperCase();
  return companyName(branding).slice(0, 2).toUpperCase();
}

export function logoMarkup(
  branding: Branding | null | undefined,
  width: number,
  alt = '',
): string {
  if (branding?.logo_url) {
    return `<img src="${escapeHtml(branding.logo_url)}" alt="${escapeHtml(
      alt || companyName(branding),
    )}" width="${width}" style="display:inline-block;max-width:100%;height:auto;border:0;outline:none;" />`;
  }
  return `<span style="display:inline-block;width:${width}px;height:${width}px;line-height:${width}px;border-radius:14px;background:${escapeHtml(
    primary(branding),
  )};color:#ffffff;text-align:center;font-size:${Math.max(
    12,
    Math.floor(width / 3),
  )}px;font-weight:800;letter-spacing:.5px;">${escapeHtml(initial(branding))}</span>`;
}

export function mergeTagsForPreview(html: string): string {
  return (html || '').replace(
    /(<[^>]*>)|(\{\{\s*([a-zA-Z0-9_]+)\s*\}\})/g,
    (_match, tag: string | undefined, _token: string | undefined, name: string | undefined) => {
      if (tag) return tag;
      const token = name || '';
      const label = MERGE_LABELS[token] || token;
      return `<span data-hs-merge-tag="{{${token}}}" contenteditable="false" style="display:inline-block;padding:1px 5px;border-radius:4px;background:#E0F2FE;color:#0369A1;font-size:.88em;font-weight:700;">${escapeHtml(
        label,
      )}</span>`;
    },
  );
}

export function cleanLegacyBodyHtml(html: string): string {
  if (typeof DOMParser === 'undefined') return html;
  try {
    const doc = new DOMParser().parseFromString(
      `<!doctype html><html lang="ar" dir="rtl"><body>${html || ''}</body></html>`,
      'text/html',
    );
    doc.querySelectorAll('[data-hs-merge-tag]').forEach((tag) => {
      tag.replaceWith(doc.createTextNode(tag.getAttribute('data-hs-merge-tag') || ''));
    });
    doc.querySelectorAll('[contenteditable]').forEach((element) => {
      element.removeAttribute('contenteditable');
    });
    doc.querySelectorAll('[data-hs-block-id]').forEach((element) => {
      element.removeAttribute('data-hs-block-id');
    });
    doc.querySelectorAll('[data-hs-editable]').forEach((element) => {
      element.removeAttribute('data-hs-editable');
    });
    doc.querySelectorAll('.hs-selected').forEach((element) => {
      element.classList.remove('hs-selected');
    });
    doc.querySelector('#hs-editor-bridge')?.remove();
    return doc.body.innerHTML;
  } catch {
    return html;
  }
}

export function replaceBrandingPlaceholders(
  html: string,
  branding?: Branding | null,
): string {
  if (!html) return '';
  const logo = logoMarkup(branding, 150, companyName(branding));
  const support = branding?.support_email
    ? `<a href="mailto:${escapeHtml(branding.support_email)}" style="color:${escapeHtml(
        primary(branding),
      )};text-decoration:none;">${escapeHtml(branding.support_email)}</a>`
    : '';
  const replacements: Record<string, string> = {
    '[LOGO]': logo,
    '[COMPANY_NAME]': escapeHtml(companyName(branding)),
    '[SUPPORT_EMAIL]': support || escapeHtml(branding?.support_email || ''),
    '[PRIMARY_COLOR]': escapeHtml(primary(branding)),
    '[YEAR]': String(new Date().getFullYear()),
  };
  let rendered = html;
  Object.entries(replacements).forEach(([token, value]) => {
    rendered = rendered.replace(new RegExp(token.replace(/[[\]]/g, '\\$&'), 'gi'), value);
  });
  return rendered;
}

function padding(block: { padding_top: number; padding_bottom: number }): string {
  return `padding-top:${block.padding_top}px;padding-bottom:${block.padding_bottom}px;`;
}

function renderText(block: EmailTextBlock, design: EmailDesign, options: RenderOptions): string {
  const content = options.forEditor ? mergeTagsForPreview(block.content) : block.content;
  const color = block.color || design.settings.text_color;
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" data-hs-editable="text" class="hs-email-text" style="${padding(
    block,
  )}text-align:${block.align};font-size:${block.font_size}px;line-height:${block.line_height};color:${escapeHtml(
    color,
  )};font-weight:${block.font_weight};">${content}</div>`;
}

function renderImage(block: EmailImageBlock, options: RenderOptions): string {
  if (!block.src.trim()) {
    if (!options.forEditor) return '';
    return `<div data-hs-block-id="${escapeHtml(
      block.id,
    )}" style="${padding(
      block,
    )}text-align:${block.align};"><div style="border:1px dashed #94A3B8;border-radius:8px;padding:28px;color:#64748B;font-size:13px;background:#F8FAFC;">صورة — أضف رابطاً من الخصائص</div></div>`;
  }
  const image = `<img src="${escapeHtml(safeUrl(block.src))}" alt="${escapeHtml(
    block.alt,
  )}" width="${block.width}" style="display:inline-block;max-width:100%;height:auto;border:0;outline:none;border-radius:${block.border_radius}px;" />`;
  const linked = block.link.trim()
    ? `<a href="${escapeHtml(safeUrl(block.link))}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">${image}</a>`
    : image;
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" style="${padding(block)}text-align:${block.align};">${linked}</div>`;
}

function renderButton(block: EmailButtonBlock, design: EmailDesign, options: RenderOptions): string {
  const label = options.forEditor
    ? mergeTagsForPreview(escapeHtml(block.label))
    : escapeHtml(block.label);
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" style="${padding(block)}text-align:${block.align};"><table role="presentation" cellpadding="0" cellspacing="0" border="0" style="display:inline-table;border-collapse:separate;"><tr><td bgcolor="${escapeHtml(
    block.background_color,
  )}" style="border-radius:${block.border_radius}px;"><a data-hs-editable="button" href="${escapeHtml(
    safeUrl(block.url),
  )}" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:${block.padding_y}px ${
    block.padding_x
  }px;font-family:${fontStack(
    design,
  )};font-size:${block.font_size}px;font-weight:700;color:${escapeHtml(
    block.text_color,
  )};text-decoration:none;border-radius:${block.border_radius}px;">${label}</a></td></tr></table></div>`;
}

function renderDivider(block: EmailDividerBlock): string {
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" style="${padding(block)}text-align:center;"><div style="display:inline-block;width:${block.width_percent}%;border-top:${block.thickness}px solid ${escapeHtml(
    block.color,
  )};font-size:0;line-height:0;">&nbsp;</div></div>`;
}

function renderSpacer(block: EmailSpacerBlock): string {
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" aria-hidden="true" style="height:${block.height}px;line-height:${block.height}px;font-size:0;">&nbsp;</div>`;
}

function renderLogo(block: EmailLogoBlock, branding?: Branding | null): string {
  const logo = logoMarkup(branding, block.width, block.alt || companyName(branding));
  const linked = block.link.trim()
    ? `<a href="${escapeHtml(safeUrl(block.link))}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">${logo}</a>`
    : logo;
  const company = block.show_company_name
    ? `<div style="font-size:13px;font-weight:800;color:${escapeHtml(
        primary(branding),
      )};margin-top:8px;">${escapeHtml(companyName(branding))}</div>`
    : '';
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" style="${padding(block)}text-align:${block.align};">${linked}${company}</div>`;
}

function renderFooter(
  block: EmailFooterBlock,
  design: EmailDesign,
  branding?: Branding | null,
): string {
  const parts: string[] = [];
  if (block.show_logo) {
    parts.push(
      `<div style="margin-bottom:12px;">${logoMarkup(branding, 42, companyName(branding))}</div>`,
    );
  }
  if (block.show_company_name) {
    parts.push(
      `<div style="font-weight:700;color:#667085;">${escapeHtml(companyName(branding))}</div>`,
    );
  }
  if (block.text.trim()) {
    parts.push(
      `<div style="margin-top:6px;">${escapeHtml(block.text).replace(/\n/g, '<br />')}</div>`,
    );
  }
  if (block.show_support_email && branding?.support_email) {
    parts.push(
      `<div style="margin-top:6px;"><a href="mailto:${escapeHtml(
        branding.support_email,
      )}" style="color:${escapeHtml(
        design.settings.link_color,
      )};text-decoration:none;">${escapeHtml(branding.support_email)}</a></div>`,
    );
  }
  parts.push(
    `<div style="margin-top:10px;font-size:11px;">&copy; ${new Date().getFullYear()} ${escapeHtml(
      companyName(branding),
    )}. All rights reserved.</div>`,
  );
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" class="hs-email-footer" style="${padding(block)}text-align:${block.align};font-size:${
    block.font_size
  }px;line-height:1.7;color:${escapeHtml(block.color)};">${parts.join('')}</div>`;
}

function renderHtml(block: EmailHtmlBlock, options: RenderOptions): string {
  const content = options.forEditor ? mergeTagsForPreview(block.html) : block.html;
  return `<div data-hs-block-id="${escapeHtml(
    block.id,
  )}" data-hs-editable="html" style="${padding(block)}">${content}</div>`;
}

function renderBlock(
  block: EmailDesignBlock,
  design: EmailDesign,
  branding: Branding | null | undefined,
  options: RenderOptions,
): string {
  switch (block.type) {
    case 'text':
      return renderText(block, design, options);
    case 'image':
      return renderImage(block, options);
    case 'button':
      return renderButton(block, design, options);
    case 'divider':
      return renderDivider(block);
    case 'spacer':
      return renderSpacer(block);
    case 'logo':
      return renderLogo(block, branding);
    case 'footer':
      return renderFooter(block, design, branding);
    case 'html':
      return renderHtml(block, options);
    default:
      return '';
  }
}

function shell(content: string, design: EmailDesign, branding?: Branding | null): string {
  const font = fontStack(design);
  const company = escapeHtml(companyName(branding));
  const preheader = escapeHtml(
    design.settings.preheader || `رسالة من ${companyName(branding)}`,
  );
  return `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /><meta name="color-scheme" content="light dark" /><meta name="supported-color-schemes" content="light dark" /><title>${company}</title><style type="text/css">html,body{margin:0;padding:0;}img{border:0;outline:none;text-decoration:none;}a{text-decoration:none;}@media only screen and (max-width:620px){.hs-email-card{width:100% !important;max-width:100% !important;}.hs-email-pad{padding-left:20px !important;padding-right:20px !important;}}@media (prefers-color-scheme:dark){.hs-email-body{background-color:#0B1220 !important;}.hs-email-card{background-color:#111A2B !important;border-color:#26364F !important;}.hs-email-text,.hs-email-footer{color:#E6EDF7 !important;}}</style></head><body class="hs-email-body" style="margin:0;padding:0;background:${escapeHtml(
    design.settings.background_color,
  )};font-family:${font};color:${escapeHtml(
    design.settings.text_color,
  )};"><div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">${preheader}</div><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${escapeHtml(
    design.settings.background_color,
  )};padding:28px 12px;"><tr><td align="center"><table role="presentation" width="${
    design.settings.width
  }" cellpadding="0" cellspacing="0" border="0" class="hs-email-card" style="width:${
    design.settings.width
  }px;max-width:${design.settings.width}px;background:${escapeHtml(
    design.settings.content_background_color,
  )};border:1px solid #E4E7EC;border-radius:${
    design.settings.border_radius
  }px;overflow:hidden;font-family:${font};"><tr><td style="height:4px;background:${escapeHtml(
    design.settings.link_color,
  )};font-size:0;line-height:0;">&nbsp;</td></tr><tr><td class="hs-email-pad" style="padding:${
    design.settings.content_padding
  }px;font-family:${font};color:${escapeHtml(
    design.settings.text_color,
  )};">${content}</td></tr></table><div style="max-width:600px;padding:14px 8px 0;font-size:11px;line-height:1.5;color:#98A2B3;text-align:center;font-family:${font};">${company} &middot; Security awareness simulation</div></td></tr></table></body></html>`;
}

export function renderEmailDesignHtml(
  design: EmailDesign,
  branding?: Branding | null,
  options: RenderOptions = {},
): string {
  if (design.mode === 'legacy') {
    let html = replaceBrandingPlaceholders(design.legacy_html || '', branding);
    if (!/<html[\s>]/i.test(html)) {
      html = `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /><style>html,body{margin:0;padding:0;}</style></head><body style="margin:0;background:${escapeHtml(
        design.settings.background_color,
      )};font-family:${fontStack(
        design,
      )};color:${escapeHtml(design.settings.text_color)};">${html}</body></html>`;
    }
    return options.forEditor ? mergeTagsForPreview(html) : html;
  }
  const content = design.blocks
    .map((block) => renderBlock(block, design, branding, options))
    .join('');
  const html = replaceBrandingPlaceholders(shell(content, design, branding), branding);
  return options.forEditor ? mergeTagsForPreview(html) : html;
}

/**
 * Remove active content from a preview document before it enters the sandboxed
 * iframe.  The backend performs the authoritative sanitisation on save.
 */
export function sanitizePreviewHtml(html: string): string {
  if (typeof DOMParser === 'undefined') return html;
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc
      .querySelectorAll('script,iframe,object,embed,form,link,meta[http-equiv]')
      .forEach((node) => node.remove());
    doc.querySelectorAll('*').forEach((node) => {
      Array.from(node.attributes).forEach((attr) => {
        const name = attr.name.toLowerCase();
        const value = attr.value.trim().toLowerCase();
        if (name.startsWith('on')) node.removeAttribute(attr.name);
        if ((name === 'href' || name === 'src') && value.startsWith('javascript:')) {
          node.removeAttribute(attr.name);
        }
        if (name === 'style' && /expression|javascript:/i.test(value)) {
          node.removeAttribute(attr.name);
        }
      });
    });
    return doc.documentElement.outerHTML;
  } catch {
    return html;
  }
}

const BRIDGE_SCRIPT = `
(function () {
  var SOURCE = 'hs-email-editor';
  function post(type, payload) {
    var message = payload || {};
    message.source = SOURCE;
    message.type = type;
    parent.postMessage(message, '*');
  }
  function clearSelection() {
    document.querySelectorAll('.hs-selected').forEach(function (el) {
      el.classList.remove('hs-selected');
    });
  }
  function markLegacy() {
    if (document.querySelector('[data-hs-block-id]')) return;
    var nodes = document.body.querySelectorAll('*');
    nodes.forEach(function (el, index) {
      el.setAttribute('data-hs-block-id', 'legacy-' + index);
      if (!el.children.length && (el.textContent || '').trim()) {
        el.setAttribute('data-hs-editable', 'legacy');
      }
    });
  }
  function cleanClone(node) {
    var clone = node.cloneNode(true);
    clone.querySelectorAll('[data-hs-merge-tag]').forEach(function (tag) {
      tag.replaceWith(document.createTextNode(tag.getAttribute('data-hs-merge-tag') || ''));
    });
    [clone].concat(Array.from(clone.querySelectorAll('*'))).forEach(function (el) {
      el.classList.remove('hs-selected');
      el.removeAttribute('contenteditable');
      if (el !== node) {
        el.removeAttribute('data-hs-block-id');
        el.removeAttribute('data-hs-editable');
      }
    });
    return clone;
  }
  document.addEventListener('click', function (event) {
    var link = event.target.closest ? event.target.closest('a') : null;
    if (link) event.preventDefault();
    var block = event.target.closest ? event.target.closest('[data-hs-block-id]') : null;
    clearSelection();
    if (block) {
      block.classList.add('hs-selected');
      post('select', { id: block.getAttribute('data-hs-block-id') });
    } else {
      post('select', { id: null });
    }
  }, true);
  document.addEventListener('dblclick', function (event) {
    var editable = event.target.closest ? event.target.closest('[data-hs-editable]') : null;
    if (!editable) return;
    event.preventDefault();
    var kind = editable.getAttribute('data-hs-editable');
    var block = editable.closest('[data-hs-block-id]');
    var blockId = block ? block.getAttribute('data-hs-block-id') : null;
    editable.setAttribute('contenteditable', 'true');
    editable.focus();
    var range = document.createRange();
    range.selectNodeContents(editable);
    var selection = window.getSelection();
    if (selection) {
      selection.removeAllRanges();
      selection.addRange(range);
    }
    function finish() {
      editable.removeAttribute('contenteditable');
      editable.removeEventListener('blur', finish);
      if (kind === 'legacy') {
        var bodyClone = document.body.cloneNode(true);
        var bridge = bodyClone.querySelector('#hs-editor-bridge');
        if (bridge) bridge.remove();
        bodyClone.querySelectorAll('[data-hs-merge-tag]').forEach(function (tag) {
          tag.replaceWith(document.createTextNode(tag.getAttribute('data-hs-merge-tag') || ''));
        });
        bodyClone.querySelectorAll('.hs-selected').forEach(function (el) {
          el.classList.remove('hs-selected');
        });
        bodyClone.querySelectorAll('[data-hs-block-id]').forEach(function (el) {
          el.removeAttribute('data-hs-block-id');
        });
        bodyClone.querySelectorAll('[data-hs-editable]').forEach(function (el) {
          el.removeAttribute('data-hs-editable');
        });
        bodyClone.querySelectorAll('[contenteditable]').forEach(function (el) {
          el.removeAttribute('contenteditable');
        });
        post('legacy', { html: bodyClone.innerHTML });
      } else {
        var clone = cleanClone(editable);
        post('edit', {
          id: blockId,
          html: clone.innerHTML,
          text: clone.textContent || ''
        });
      }
    }
    editable.addEventListener('blur', finish);
  }, true);
  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (data.source !== 'hs-editor-parent') return;
    if (data.type === 'dark') {
      document.documentElement.classList.toggle('hs-dark-preview', !!data.value);
    }
    if (data.type === 'select') {
      clearSelection();
      if (data.id) {
        var target = document.querySelector('[data-hs-block-id="' + String(data.id).replace(/"/g, '') + '"]');
        if (target) target.classList.add('hs-selected');
      }
    }
  });
  markLegacy();
  post('ready');
})();
`;

const EDITOR_STYLE = `
<style id="hs-editor-style">
  html.hs-dark-preview body { background:#0B1220 !important; }
  html.hs-dark-preview table, html.hs-dark-preview td, html.hs-dark-preview div { background-color: transparent !important; }
  html.hs-dark-preview * { color:#E6EDF7 !important; border-color:#2A3A55 !important; }
  html.hs-dark-preview a { color:#7DD3FC !important; }
  .hs-selected { outline: 2px dashed #00F0FF !important; outline-offset: 3px !important; }
  [data-hs-editable]:hover { cursor: text; }
  [data-hs-block-id]:hover { cursor: pointer; }
</style>
`;

/** Add the click/edit bridge and dark-mode preview styles to a document. */
export function buildEditorDocument(html: string, darkMode: boolean): string {
  let documentHtml = sanitizePreviewHtml(html);
  if (!/<html[\s>]/i.test(documentHtml)) {
    documentHtml = `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8" /></head><body style="margin:0;background:#F2F4F7;">${documentHtml}</body></html>`;
  }
  if (!documentHtml.includes('id="hs-editor-style"')) {
    documentHtml = documentHtml.replace(/<\/head>/i, `${EDITOR_STYLE}</head>`);
  }
  if (!documentHtml.includes('id="hs-editor-bridge"')) {
    documentHtml = documentHtml.replace(
      /<\/body>/i,
      `<script id="hs-editor-bridge">${BRIDGE_SCRIPT}</script></body>`,
    );
  }
  if (darkMode) {
    documentHtml = documentHtml.replace(
      /<html([^>]*)>/i,
      '<html$1 class="hs-dark-preview">',
    );
  }
  return documentHtml;
}

export function designToBodyHtml(design: EmailDesign, branding?: Branding | null): string {
  return renderEmailDesignHtml(design, branding, { forEditor: false });
}

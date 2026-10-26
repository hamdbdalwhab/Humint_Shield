/**
 * Shared types and defaults for the no-code email editor.
 *
 * The JSON contract mirrors `backend/app/schemas/email_design.py`.  The backend
 * remains authoritative: the browser uses these values for instant preview and
 * the backend re-validates/recompiles every save.
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

export const MERGE_TAGS: Array<{ token: string; label: string; description: string }> = [
  { token: 'first_name', label: 'الاسم الأول', description: 'First Name' },
  { token: 'last_name', label: 'اسم العائلة', description: 'Last Name' },
  { token: 'company_name', label: 'اسم الشركة', description: 'Company Name' },
  { token: 'department', label: 'القسم', description: 'Department' },
  { token: 'manager_name', label: 'المدير', description: 'Manager Name' },
  { token: 'email', label: 'البريد الإلكتروني', description: 'Email' },
  { token: 'tracking_url', label: 'رابط التتبع', description: 'Tracking URL' },
];

export const FONT_OPTIONS = [
  { value: 'Cairo', label: 'Cairo — عربي حديث' },
  { value: 'Tajawal', label: 'Tajawal — عربي' },
  { value: 'Segoe UI', label: 'Segoe UI' },
  { value: 'Tahoma', label: 'Tahoma' },
  { value: 'Arial', label: 'Arial' },
  { value: 'Georgia', label: 'Georgia' },
  { value: 'Verdana', label: 'Verdana' },
];

export const BLOCK_LABELS: Record<string, string> = {
  text: 'نص',
  image: 'صورة',
  button: 'زر',
  divider: 'فاصل',
  spacer: 'مسافة',
  logo: 'الشعار',
  footer: 'التذييل',
  html: 'HTML متقدم',
};

export function newId(): string {
  const cryptoObject = globalThis.crypto as Crypto | undefined;
  if (cryptoObject?.randomUUID) {
    return cryptoObject.randomUUID().replace(/-/g, '').slice(0, 24);
  }
  return `b${Math.random().toString(36).slice(2, 12)}${Date.now().toString(36)}`.slice(0, 24);
}

const BASE = {
  padding_top: 0,
  padding_bottom: 12,
  align: 'right' as const,
};

export function createBlock(type: EmailDesignBlock['type'], branding?: Branding | null): EmailDesignBlock {
  const primary = branding?.primary_color || '#0F6CBD';
  switch (type) {
    case 'text':
      return {
        ...BASE,
        id: newId(),
        type: 'text',
        content: '<p style="margin:0 0 12px;">اكتب النص هنا…</p>',
        font_size: 16,
        color: null,
        font_weight: 'normal',
        line_height: 1.7,
      } satisfies EmailTextBlock;
    case 'image':
      return {
        ...BASE,
        id: newId(),
        type: 'image',
        src: '',
        alt: 'صورة',
        link: '',
        width: 520,
        border_radius: 8,
      } satisfies EmailImageBlock;
    case 'button':
      return {
        ...BASE,
        id: newId(),
        type: 'button',
        label: 'اتخاذ إجراء',
        url: '{{tracking_url}}',
        background_color: primary,
        text_color: '#FFFFFF',
        border_radius: 8,
        font_size: 15,
        padding_x: 28,
        padding_y: 13,
      } satisfies EmailButtonBlock;
    case 'divider':
      return {
        ...BASE,
        id: newId(),
        type: 'divider',
        color: '#EAECF0',
        thickness: 1,
        width_percent: 100,
      } satisfies EmailDividerBlock;
    case 'spacer':
      return {
        ...BASE,
        id: newId(),
        type: 'spacer',
        height: 24,
      } satisfies EmailSpacerBlock;
    case 'logo':
      return {
        ...BASE,
        id: newId(),
        type: 'logo',
        width: 150,
        link: '',
        alt: branding?.company_name || 'الشعار',
        show_company_name: true,
      } satisfies EmailLogoBlock;
    case 'footer':
      return {
        ...BASE,
        id: newId(),
        type: 'footer',
        text: 'رسالة خدمية أُرسلت إلى {{email}}.',
        show_company_name: true,
        show_support_email: true,
        show_logo: false,
        font_size: 12,
        color: '#98A2B3',
        padding_top: 18,
        padding_bottom: 4,
      } satisfies EmailFooterBlock;
    case 'html':
      return {
        ...BASE,
        id: newId(),
        type: 'html',
        html: '<p style="margin:0;">أضف محتوى HTML آمناً هنا.</p>',
      } satisfies EmailHtmlBlock;
    default:
      return {
        ...BASE,
        id: newId(),
        type: 'text',
        content: '<p style="margin:0 0 12px;">اكتب النص هنا…</p>',
        font_size: 16,
        color: null,
        font_weight: 'normal',
        line_height: 1.7,
      } satisfies EmailTextBlock;
  }
}

export function createDefaultDesign(branding?: Branding | null): EmailDesign {
  const primary = branding?.primary_color || '#0F6CBD';
  return {
    version: 1,
    mode: 'blocks',
    settings: {
      background_color: '#F2F4F7',
      content_background_color: '#FFFFFF',
      font_family: 'Cairo',
      text_color: '#344054',
      link_color: primary,
      width: 600,
      content_padding: 32,
      border_radius: 14,
      preheader: `رسالة من ${branding?.company_name || 'شركتك'}`,
    },
    blocks: [
      createBlock('logo', branding),
      {
        ...createBlock('text', branding),
        content:
          '<p style="margin:0 0 14px;">مرحباً {{first_name}}،</p><p style="margin:0 0 14px;">لديك مستند جديد يحتاج مراجعتك قبل نهاية اليوم.</p>',
      } as EmailTextBlock,
      {
        ...createBlock('button', branding),
        label: 'فتح المستند',
        background_color: primary,
      } as EmailButtonBlock,
      {
        ...createBlock('text', branding),
        content: '<p style="margin:0;">شكراً،<br /><strong>{{company_name}}</strong></p>',
      } as EmailTextBlock,
      createBlock('footer', branding),
    ],
    legacy_html: null,
  };
}

export function legacyDesign(html: string, primaryColor = '#0F6CBD'): EmailDesign {
  return {
    version: 1,
    mode: 'legacy',
    settings: {
      background_color: '#F2F4F7',
      content_background_color: '#FFFFFF',
      font_family: 'Cairo',
      text_color: '#344054',
      link_color: primaryColor,
      width: 600,
      content_padding: 32,
      border_radius: 14,
      preheader: '',
    },
    blocks: [],
    legacy_html: html || '',
  };
}

export function cloneDesign(design: EmailDesign): EmailDesign {
  return JSON.parse(JSON.stringify(design)) as EmailDesign;
}

export function stripHtml(value: string): string {
  return value
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/[ \t]+/g, ' ')
    .trim();
}

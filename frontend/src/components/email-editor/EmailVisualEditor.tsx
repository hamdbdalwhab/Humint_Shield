/**
 * WYSIWYG no-code email editor.
 *
 * Layout: block palette + draggable layer list on the left, live email canvas
 * in a sandboxed iframe in the centre, and block/canvas properties on the
 * right.  Clicking an element inside the iframe selects it; double-clicking
 * enters direct inline editing.  The iframe bridge posts sanitised edits back
 * to React, so the saved JSON remains the source of truth.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Building2,
  Code2,
  GripVertical,
  Image as ImageIcon,
  Layers,
  Link2,
  Minus,
  Monitor,
  Moon,
  MousePointerClick,
  MoveVertical,
  Palette,
  PanelBottom,
  Plus,
  Send,
  Smartphone,
  Sun,
  Tablet,
  Trash2,
  Type,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';

import type {
  Branding,
  EmailDesign,
  EmailDesignBlock,
  EmailDesignSettings,
  EmailHtmlBlock,
  TemplateTestSendResult,
} from '@/types';

import { buildEditorDocument, cleanLegacyBodyHtml, renderEmailDesignHtml } from './renderEmail';
import {
  BLOCK_LABELS,
  FONT_OPTIONS,
  MERGE_TAGS,
  cloneDesign,
  createBlock,
  createDefaultDesign,
  newId,
  stripHtml,
} from './types';

interface EmailVisualEditorProps {
  design: EmailDesign;
  branding: Branding | null;
  onChange: (design: EmailDesign) => void;
  subject: string;
  onTestSend: () => void;
  testSending: boolean;
  testResult: TemplateTestSendResult | null;
  disabled?: boolean;
}

type Device = 'desktop' | 'tablet' | 'mobile';
type BlockType = EmailDesignBlock['type'];

const PALETTE: Array<{ type: BlockType; label: string; icon: typeof Type; hint: string }> = [
  { type: 'text', label: 'نص', icon: Type, hint: 'فقرة نصية غنية' },
  { type: 'image', label: 'صورة', icon: ImageIcon, hint: 'صورة قابلة للنقر' },
  { type: 'button', label: 'زر', icon: MousePointerClick, hint: 'زر إجراء رئيسي' },
  { type: 'divider', label: 'فاصل', icon: Minus, hint: 'خط فاصل' },
  { type: 'spacer', label: 'مسافة', icon: MoveVertical, hint: 'مساحة رأسية' },
  { type: 'logo', label: 'الشعار', icon: Building2, hint: 'شعار المؤسسة الديناميكي' },
];

const BLOCK_ICONS: Record<string, typeof Type> = {
  text: Type,
  image: ImageIcon,
  button: MousePointerClick,
  divider: Minus,
  spacer: MoveVertical,
  logo: Building2,
  footer: PanelBottom,
  html: Code2,
};

function ColorInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <TextField
      label={label}
      size="small"
      fullWidth
      value={value}
      onChange={(event) => onChange(event.target.value)}
      InputProps={{
        startAdornment: (
          <Box
            component="input"
            type="color"
            value={/^#[0-9a-f]{6}$/i.test(value) ? value : '#0F6CBD'}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
            sx={{
              width: 28,
              height: 28,
              p: 0,
              border: '1px solid rgba(255,255,255,.18)',
              borderRadius: 1,
              bgcolor: 'transparent',
              cursor: 'pointer',
              mr: 0.5,
            }}
          />
        ),
        sx: { fontFamily: 'Consolas, monospace', fontSize: '0.78rem' },
      }}
    />
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <Typography
      variant="caption"
      sx={{
        display: 'block',
        color: 'text.secondary',
        fontWeight: 800,
        letterSpacing: '.04em',
        textTransform: 'uppercase',
        mt: 0.5,
      }}
    >
      {children}
    </Typography>
  );
}

function SortableLayer({
  block,
  selected,
  onSelect,
}: {
  block: EmailDesignBlock;
  selected: boolean;
  onSelect: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: block.id,
  });
  const Icon = BLOCK_ICONS[block.type] || Type;
  return (
    <Box
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      onClick={onSelect}
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.75,
        px: 1,
        py: 0.65,
        borderRadius: 1.5,
        cursor: 'pointer',
        opacity: isDragging ? 0.55 : 1,
        border: `1px solid ${selected ? 'rgba(0,240,255,.45)' : 'rgba(255,255,255,.07)'}`,
        bgcolor: selected ? 'rgba(0,240,255,.09)' : 'rgba(255,255,255,.025)',
        '&:hover': { bgcolor: 'rgba(255,255,255,.06)' },
      }}
    >
      <Box
        {...attributes}
        {...listeners}
        sx={{ display: 'grid', placeItems: 'center', color: 'text.disabled', cursor: 'grab' }}
        aria-label="إعادة ترتيب"
      >
        <GripVertical size={14} />
      </Box>
      <Icon size={14} color={selected ? '#00F0FF' : '#94A3B8'} />
      <Typography sx={{ fontSize: '0.73rem', fontWeight: 700, flex: 1 }}>
        {BLOCK_LABELS[block.type] || block.type}
      </Typography>
      <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.58rem' }}>
        {block.id.slice(0, 4)}
      </Typography>
    </Box>
  );
}

function withLegacyBody(fullHtml: string, bodyHtml: string): string {
  if (typeof DOMParser === 'undefined') return bodyHtml;
  const doc = new DOMParser().parseFromString(
    fullHtml || '<!doctype html><html lang="ar" dir="rtl"><body></body></html>',
    'text/html',
  );
  doc.body.innerHTML = bodyHtml;
  return `<!DOCTYPE html>${doc.documentElement.outerHTML}`;
}

export function EmailVisualEditor({
  design,
  branding,
  onChange,
  subject,
  onTestSend,
  testSending,
  testResult,
  disabled = false,
}: EmailVisualEditorProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [device, setDevice] = useState<Device>('desktop');
  const [darkMode, setDarkMode] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const selectedBlock = useMemo(
    () => design.blocks.find((block) => block.id === selectedId) ?? null,
    [design.blocks, selectedId],
  );
  const isLegacy = design.mode === 'legacy';
  const iframeDocument = useMemo(
    () => buildEditorDocument(renderEmailDesignHtml(design, branding, { forEditor: true }), darkMode),
    [branding, darkMode, design],
  );

  const syncIframe = useCallback(() => {
    const frame = iframeRef.current?.contentWindow;
    if (!frame) return;
    frame.postMessage({ source: 'hs-editor-parent', type: 'dark', value: darkMode }, '*');
    frame.postMessage({ source: 'hs-editor-parent', type: 'select', id: selectedId }, '*');
  }, [darkMode, selectedId]);

  useEffect(() => {
    syncIframe();
  }, [syncIframe]);

  const update = useCallback(
    (next: EmailDesign) => {
      if (disabled) return;
      onChange(next);
    },
    [disabled, onChange],
  );

  const patchSettings = useCallback(
    (patch: Partial<EmailDesignSettings>) => {
      update({ ...design, settings: { ...design.settings, ...patch } });
    },
    [design, update],
  );

  const patchBlock = useCallback(
    (id: string, patch: Partial<EmailDesignBlock>) => {
      update({
        ...design,
        blocks: design.blocks.map((block) =>
          block.id === id ? ({ ...block, ...patch } as EmailDesignBlock) : block,
        ),
      });
    },
    [design, update],
  );

  const addBlock = useCallback(
    (type: BlockType) => {
      const block = createBlock(type, branding);
      const next = cloneDesign(design);
      next.blocks = [...next.blocks, block];
      update(next);
      setSelectedId(block.id);
    },
    [branding, design, update],
  );

  const removeSelected = useCallback(() => {
    if (!selectedBlock) return;
    update({ ...design, blocks: design.blocks.filter((block) => block.id !== selectedBlock.id) });
    setSelectedId(null);
  }, [design, selectedBlock, update]);

  const insertMergeTag = useCallback(
    (token: string) => {
      const snippet = `{{${token}}}`;
      if (isLegacy) {
        const legacy = design.legacy_html || '';
        const next = /<\/body>/i.test(legacy)
          ? legacy.replace(/<\/body>/i, `<p style="margin:0 0 12px;">${snippet}</p></body>`)
          : `${legacy}<p style="margin:0 0 12px;">${snippet}</p>`;
        update({ ...design, legacy_html: next });
        return;
      }
      if (!selectedBlock) {
        const block = createBlock('text', branding);
        if (block.type === 'text') {
          block.content = `<p style="margin:0 0 12px;">${snippet}</p>`;
        }
        update({ ...design, blocks: [...design.blocks, block] });
        setSelectedId(block.id);
        return;
      }
      if (selectedBlock.type === 'text') {
        patchBlock(selectedBlock.id, { content: `${selectedBlock.content}${snippet}` });
      } else if (selectedBlock.type === 'button') {
        patchBlock(selectedBlock.id, { label: `${selectedBlock.label}${snippet}` });
      } else if (selectedBlock.type === 'html') {
        patchBlock(selectedBlock.id, { html: `${selectedBlock.html}${snippet}` });
      } else {
        toast('اختر كتلة نصية أو زراً لإدراج المتغيّر');
      }
    },
    [branding, design, isLegacy, patchBlock, selectedBlock, update],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = design.blocks.findIndex((block) => block.id === active.id);
      const newIndex = design.blocks.findIndex((block) => block.id === over.id);
      if (oldIndex < 0 || newIndex < 0) return;
      update({ ...design, blocks: arrayMove(design.blocks, oldIndex, newIndex) });
    },
    [design, update],
  );

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as {
        source?: string;
        type?: string;
        id?: string | null;
        html?: string;
        text?: string;
      };
      if (!data || data.source !== 'hs-email-editor') return;
      if (data.type === 'select') {
        setSelectedId(data.id ?? null);
        return;
      }
      if (data.type === 'legacy' && typeof data.html === 'string') {
        update({
          ...design,
          legacy_html: withLegacyBody(design.legacy_html || '', cleanLegacyBodyHtml(data.html)),
        });
        return;
      }
      if (data.type === 'edit' && data.id) {
        const block = design.blocks.find((item) => item.id === data.id);
        if (!block) return;
        if (block.type === 'text' && typeof data.html === 'string') {
          patchBlock(block.id, { content: data.html });
        } else if (block.type === 'button') {
          patchBlock(block.id, { label: stripHtml(data.text || data.html || '') });
        } else if (block.type === 'html' && typeof data.html === 'string') {
          patchBlock(block.id, { html: data.html });
        }
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [design, patchBlock, update]);

  const convertLegacy = useCallback(() => {
    if (typeof DOMParser === 'undefined') return;
    const doc = new DOMParser().parseFromString(design.legacy_html || '', 'text/html');
    const content = doc.body.innerHTML;
    const base = createDefaultDesign(branding);
    const htmlBlock = createBlock('html', branding) as EmailHtmlBlock;
    htmlBlock.html = content;
    htmlBlock.id = newId();
    update({
      ...base,
      settings: { ...design.settings },
      blocks: [createBlock('logo', branding), htmlBlock, createBlock('footer', branding)],
      mode: 'blocks',
      legacy_html: null,
    });
    setSelectedId(null);
    toast.success('تم تحويل المحتوى إلى كتل مرئية');
  }, [branding, design, update]);

  const canvasWidth = device === 'desktop' ? '100%' : device === 'tablet' ? 768 : 390;

  return (
    <Box
      sx={{
        border: '1px solid rgba(255,255,255,.1)',
        borderRadius: 3,
        overflow: 'hidden',
        bgcolor: 'rgba(4,9,18,.62)',
      }}
    >
      <Stack
        direction={{ xs: 'column', lg: 'row' }}
        spacing={1}
        alignItems={{ xs: 'stretch', lg: 'center' }}
        sx={{
          px: 1.5,
          py: 1.1,
          borderBottom: '1px solid rgba(255,255,255,.08)',
          bgcolor: 'rgba(9,16,30,.86)',
        }}
      >
        <Stack direction="row" spacing={0.5} alignItems="center">
          <Tooltip title="سطح المكتب">
            <IconButton
              size="small"
              color={device === 'desktop' ? 'primary' : 'default'}
              onClick={() => setDevice('desktop')}
            >
              <Monitor size={17} />
            </IconButton>
          </Tooltip>
          <Tooltip title="جهاز لوحي">
            <IconButton
              size="small"
              color={device === 'tablet' ? 'primary' : 'default'}
              onClick={() => setDevice('tablet')}
            >
              <Tablet size={17} />
            </IconButton>
          </Tooltip>
          <Tooltip title="هاتف">
            <IconButton
              size="small"
              color={device === 'mobile' ? 'primary' : 'default'}
              onClick={() => setDevice('mobile')}
            >
              <Smartphone size={17} />
            </IconButton>
          </Tooltip>
          <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
          <Tooltip title={darkMode ? 'معاينة فاتحة' : 'معاينة الوضع الداكن'}>
            <IconButton size="small" onClick={() => setDarkMode((current) => !current)}>
              {darkMode ? <Sun size={17} /> : <Moon size={17} />}
            </IconButton>
          </Tooltip>
        </Stack>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography noWrap variant="caption" sx={{ color: 'text.secondary' }}>
            {subject || 'بدون موضوع — أضف موضوع الرسالة بالأعلى'}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="contained"
          startIcon={testSending ? <CircularProgress size={14} color="inherit" /> : <Send size={14} />}
          disabled={disabled || testSending || !subject.trim()}
          onClick={onTestSend}
          sx={{
            background: 'linear-gradient(135deg, #00F0FF 0%, #7C4DFF 100%)',
            color: '#04101C',
            fontWeight: 900,
            whiteSpace: 'nowrap',
          }}
        >
          {testSending ? 'جارٍ الإرسال…' : 'إرسال نسخة تجريبية إليّ'}
        </Button>
      </Stack>

      {testResult ? (
        <Alert severity={testResult.success ? 'success' : 'error'} sx={{ borderRadius: 0 }}>
          {testResult.success
            ? `تم إرسال النسخة التجريبية إلى ${testResult.to_email}.`
            : `تعذّر الإرسال إلى ${testResult.to_email}: ${testResult.error || 'خطأ غير معروف'}`}
        </Alert>
      ) : null}

      <Box
        dir="ltr"
        sx={{
          display: 'grid',
          // Keep the conventional builder layout (palette left, properties
          // right) even though the surrounding application is RTL.  Each
          // panel restores RTL internally so Arabic labels stay natural.
          // Use the HTML `dir` attribute because MUI's RTL CSS plugin flips
          // the `direction` declaration inside `sx`.
          gridTemplateColumns: { xs: '1fr', lg: '228px minmax(0, 1fr) 318px' },
          minHeight: 640,
        }}
      >
        {/* ------------------------------ left rail ------------------------------ */}
        <Box
          dir="rtl"
          sx={{
            borderRight: { lg: '1px solid rgba(255,255,255,.08)' },
            borderBottom: { xs: '1px solid rgba(255,255,255,.08)', lg: 0 },
            p: 1.25,
            bgcolor: 'rgba(255,255,255,.018)',
          }}
        >
          <Stack direction="row" alignItems="center" spacing={0.7} sx={{ mb: 1 }}>
            <Plus size={14} color="#00F0FF" />
            <Typography sx={{ fontSize: '0.76rem', fontWeight: 800 }}>إضافة كتلة</Typography>
          </Stack>
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 0.7 }}>
            {PALETTE.map((item) => {
              const Icon = item.icon;
              return (
                <Tooltip key={item.type} title={item.hint} arrow>
                  <Button
                    type="button"
                    variant="outlined"
                    size="small"
                    onClick={() => addBlock(item.type)}
                    disabled={disabled || isLegacy}
                    sx={{
                      justifyContent: 'flex-start',
                      gap: 0.65,
                      px: 0.8,
                      py: 0.75,
                      minWidth: 0,
                      fontSize: '0.68rem',
                      fontWeight: 700,
                      borderColor: 'rgba(255,255,255,.1)',
                      color: 'text.primary',
                    }}
                  >
                    <Icon size={14} color="#7DD3FC" />
                    {item.label}
                  </Button>
                </Tooltip>
              );
            })}
          </Box>
          {isLegacy ? (
            <Button
              type="button"
              size="small"
              fullWidth
              variant="text"
              onClick={convertLegacy}
              sx={{ mt: 0.8, fontSize: '0.66rem' }}
            >
              تحويل إلى كتل مرئية
            </Button>
          ) : null}

          <Divider sx={{ my: 1.4 }} />
          <Stack direction="row" alignItems="center" spacing={0.7} sx={{ mb: 0.8 }}>
            <Layers size={14} color="#B388FF" />
            <Typography sx={{ fontSize: '0.76rem', fontWeight: 800 }}>الطبقات</Typography>
            <Chip
              size="small"
              label={design.blocks.length}
              sx={{ height: 18, fontSize: '0.58rem', ml: 'auto' }}
            />
          </Stack>
          {isLegacy ? (
            <Paper
              variant="outlined"
              sx={{ p: 1, bgcolor: 'rgba(255,255,255,.02)', borderColor: 'rgba(255,255,255,.08)' }}
            >
              <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1.7 }}>
                هذا قالب HTML قديم محفوظ. انقر نقراً مزدوجاً على أي نص داخل المعاينة لتعديله، أو
                حوّله إلى كتل مرئية.
              </Typography>
            </Paper>
          ) : (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext
                items={design.blocks.map((block) => block.id)}
                strategy={verticalListSortingStrategy}
              >
                <Stack spacing={0.55}>
                  {design.blocks.map((block) => (
                    <SortableLayer
                      key={block.id}
                      block={block}
                      selected={block.id === selectedId}
                      onSelect={() => setSelectedId(block.id)}
                    />
                  ))}
                </Stack>
              </SortableContext>
            </DndContext>
          )}
        </Box>

        {/* ------------------------------ canvas ------------------------------ */}
        <Box
          dir="rtl"
          sx={{
            minWidth: 0,
            p: { xs: 1.25, sm: 2 },
            background:
              'radial-gradient(circle at 50% 0%, rgba(0,240,255,.07), transparent 46%), repeating-linear-gradient(45deg, rgba(255,255,255,.018) 0 1px, transparent 1px 18px)',
            overflow: 'auto',
          }}
        >
          <Box sx={{ maxWidth: 940, mx: 'auto' }}>
            <Stack direction="row" alignItems="center" justifyContent="center" spacing={0.8} sx={{ mb: 1 }}>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                {device === 'desktop' ? 'سطح المكتب' : device === 'tablet' ? 'جهاز لوحي' : 'هاتف'}
              </Typography>
              <Chip
                size="small"
                label={darkMode ? 'Dark Mode' : 'Light Mode'}
                sx={{ height: 19, fontSize: '0.58rem' }}
              />
            </Stack>
            <Box
              sx={{
                width: canvasWidth,
                maxWidth: '100%',
                mx: 'auto',
                height: 590,
                borderRadius: 2,
                overflow: 'hidden',
                bgcolor: '#fff',
                boxShadow: '0 22px 60px rgba(0,0,0,.45)',
                border: '1px solid rgba(255,255,255,.18)',
              }}
            >
              <iframe
                ref={iframeRef}
                title="Visual email canvas"
                srcDoc={iframeDocument}
                sandbox="allow-scripts"
                onLoad={syncIframe}
                style={{ width: '100%', height: '100%', border: 0, background: '#fff' }}
              />
            </Box>
            <Typography
              variant="caption"
              sx={{ display: 'block', textAlign: 'center', color: 'text.secondary', mt: 1 }}
            >
              انقر لتحديد أي عنصر، وانقر نقراً مزدوجاً لتعديل النص مباشرة.
            </Typography>
          </Box>
        </Box>

        {/* ------------------------------ properties ------------------------------ */}
        <Box
          dir="rtl"
          sx={{
            borderLeft: { lg: '1px solid rgba(255,255,255,.08)' },
            borderTop: { xs: '1px solid rgba(255,255,255,.08)', lg: 0 },
            p: 1.4,
            bgcolor: 'rgba(255,255,255,.018)',
            maxHeight: 720,
            overflow: 'auto',
          }}
        >
          <Stack direction="row" alignItems="center" spacing={0.7} sx={{ mb: 1 }}>
            <Palette size={14} color="#FFB020" />
            <Typography sx={{ fontSize: '0.78rem', fontWeight: 800 }}>
              {selectedBlock ? `خصائص: ${BLOCK_LABELS[selectedBlock.type] || selectedBlock.type}` : 'إعدادات اللوحة'}
            </Typography>
            {selectedBlock ? (
              <Tooltip title="حذف الكتلة">
                <IconButton size="small" color="error" onClick={removeSelected} sx={{ ml: 'auto' }}>
                  <Trash2 size={14} />
                </IconButton>
              </Tooltip>
            ) : null}
          </Stack>

          <Stack spacing={1.1}>
            {selectedBlock ? (
              <BlockProperties block={selectedBlock} design={design} patchBlock={patchBlock} />
            ) : isLegacy ? (
              <Paper
                variant="outlined"
                sx={{ p: 1.25, bgcolor: 'rgba(255,255,255,.02)', borderColor: 'rgba(255,255,255,.08)' }}
              >
                <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1.8 }}>
                  القالب القديم يُعرض كما هو. يمكنك تعديل النصوص مباشرة داخل المعاينة، أو استخدام
                  زر «تحويل إلى كتل مرئية» للانتقال إلى المحرر الكامل.
                </Typography>
              </Paper>
            ) : (
              <CanvasProperties settings={design.settings} patchSettings={patchSettings} />
            )}

            <Divider />
            <SectionLabel>إدراج متغيّر ديناميكي</SectionLabel>
            <TextField
              select
              size="small"
              fullWidth
              label="Merge tag"
              value=""
              onChange={(event) => {
                if (event.target.value) insertMergeTag(event.target.value);
              }}
              helperText="يُحفظ المتغيّر في HTML ويُعرض بالعربية داخل المحرر."
            >
              {MERGE_TAGS.map((tag) => (
                <MenuItem key={tag.token} value={tag.token}>
                  {tag.label} — {`{{${tag.token}}}`}
                </MenuItem>
              ))}
            </TextField>

            <Divider />
            <SectionLabel>الهوية البصرية</SectionLabel>
            <Paper
              variant="outlined"
              sx={{
                p: 1.1,
                borderColor: alpha(branding?.primary_color || '#0F6CBD', 0.28),
                bgcolor: alpha(branding?.primary_color || '#0F6CBD', 0.06),
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center">
                {branding?.logo_url ? (
                  <Box
                    component="img"
                    src={branding.logo_url}
                    alt={branding.company_name}
                    sx={{ width: 42, height: 42, objectFit: 'contain', borderRadius: 1, bgcolor: '#fff' }}
                  />
                ) : (
                  <Box
                    sx={{
                      width: 42,
                      height: 42,
                      borderRadius: 1.2,
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: branding?.primary_color || '#0F6CBD',
                      color: '#fff',
                      fontWeight: 900,
                      fontSize: '0.8rem',
                    }}
                  >
                    {(branding?.company_name || 'H').slice(0, 2)}
                  </Box>
                )}
                <Box sx={{ minWidth: 0 }}>
                  <Typography noWrap sx={{ fontWeight: 800, fontSize: '0.78rem' }}>
                    {branding?.company_name || 'شركتك'}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {branding?.support_email || 'لم يُضف بريد دعم بعد'}
                  </Typography>
                </Box>
              </Stack>
              <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 1 }}>
                تُطبّق تلقائياً على القوالب الجديدة. يمكنك تجاوز اللون داخل خصائص الزر.
              </Typography>
            </Paper>

            <Divider />
            <SectionLabel>رابط سريع</SectionLabel>
            <Button
              type="button"
              size="small"
              variant="outlined"
              startIcon={<Link2 size={14} />}
              onClick={() => window.open('/settings?tab=branding', '_blank', 'noopener')}
              sx={{ justifyContent: 'flex-start', fontSize: '0.68rem' }}
            >
              فتح إعدادات العلامة التجارية
            </Button>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
}

function CanvasProperties({
  settings,
  patchSettings,
}: {
  settings: EmailDesignSettings;
  patchSettings: (patch: Partial<EmailDesignSettings>) => void;
}) {
  return (
    <Stack spacing={1.1}>
      <SectionLabel>خلفية الرسالة</SectionLabel>
      <ColorInput
        label="لون خلفية البريد"
        value={settings.background_color}
        onChange={(value) => patchSettings({ background_color: value })}
      />
      <ColorInput
        label="لون خلفية المحتوى"
        value={settings.content_background_color}
        onChange={(value) => patchSettings({ content_background_color: value })}
      />
      <TextField
        select
        size="small"
        fullWidth
        label="الخط العام"
        value={settings.font_family}
        onChange={(event) => patchSettings({ font_family: event.target.value })}
      >
        {FONT_OPTIONS.map((font) => (
          <MenuItem key={font.value} value={font.value}>
            {font.label}
          </MenuItem>
        ))}
      </TextField>
      <ColorInput
        label="لون النص"
        value={settings.text_color}
        onChange={(value) => patchSettings({ text_color: value })}
      />
      <ColorInput
        label="لون الروابط والتمييز"
        value={settings.link_color}
        onChange={(value) => patchSettings({ link_color: value })}
      />
      <TextField
        size="small"
        fullWidth
        type="number"
        label="عرض البريد (px)"
        value={settings.width}
        onChange={(event) =>
          patchSettings({ width: Math.max(320, Math.min(900, Number(event.target.value) || 600)) })
        }
      />
      <TextField
        size="small"
        fullWidth
        type="number"
        label="حشوة المحتوى (px)"
        value={settings.content_padding}
        onChange={(event) =>
          patchSettings({
            content_padding: Math.max(8, Math.min(80, Number(event.target.value) || 32)),
          })
        }
      />
      <TextField
        size="small"
        fullWidth
        label="Preheader"
        value={settings.preheader}
        onChange={(event) => patchSettings({ preheader: event.target.value })}
      />
    </Stack>
  );
}

function BlockProperties({
  block,
  design,
  patchBlock,
}: {
  block: EmailDesignBlock;
  design: EmailDesign;
  patchBlock: (id: string, patch: Partial<EmailDesignBlock>) => void;
}) {
  const common = (
    <>
      <SectionLabel>المحاذاة والحشوة</SectionLabel>
      <Stack direction="row" spacing={0.4}>
        {(
          [
            ['right', AlignRight],
            ['center', AlignCenter],
            ['left', AlignLeft],
          ] as const
        ).map(([value, Icon]) => (
          <Button
            key={value}
            type="button"
            size="small"
            variant={block.align === value ? 'contained' : 'outlined'}
            onClick={() => patchBlock(block.id, { align: value })}
            sx={{ minWidth: 0, flex: 1, py: 0.55 }}
          >
            <Icon size={15} />
          </Button>
        ))}
      </Stack>
      <Stack direction="row" spacing={0.8}>
        <TextField
          size="small"
          type="number"
          label="حشوة أعلى"
          value={block.padding_top}
          onChange={(event) => patchBlock(block.id, { padding_top: Number(event.target.value) || 0 })}
        />
        <TextField
          size="small"
          type="number"
          label="حشوة أسفل"
          value={block.padding_bottom}
          onChange={(event) =>
            patchBlock(block.id, { padding_bottom: Number(event.target.value) || 0 })
          }
        />
      </Stack>
    </>
  );

  switch (block.type) {
    case 'text':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>المحتوى</SectionLabel>
          <TextField
            multiline
            minRows={5}
            size="small"
            fullWidth
            label="نص الكتلة (HTML بسيط)"
            value={block.content}
            onChange={(event) => patchBlock(block.id, { content: event.target.value })}
            InputProps={{ sx: { direction: 'rtl', fontSize: '0.8rem' } }}
          />
          <Stack direction="row" spacing={0.8}>
            <TextField
              size="small"
              type="number"
              label="حجم الخط"
              value={block.font_size}
              onChange={(event) =>
                patchBlock(block.id, { font_size: Number(event.target.value) || 16 })
              }
            />
            <ColorInput
              label="لون النص"
              value={block.color || design.settings.text_color}
              onChange={(value) => patchBlock(block.id, { color: value })}
            />
          </Stack>
          <Stack direction="row" spacing={0.8}>
            <TextField
              select
              size="small"
              label="الوزن"
              value={block.font_weight}
              onChange={(event) =>
                patchBlock(block.id, {
                  font_weight: event.target.value as 'normal' | 'bold',
                })
              }
            >
              <MenuItem value="normal">عادي</MenuItem>
              <MenuItem value="bold">عريض</MenuItem>
            </TextField>
            <TextField
              size="small"
              type="number"
              label="تباعد الأسطر"
              value={block.line_height}
              inputProps={{ step: 0.1, min: 1, max: 3 }}
              onChange={(event) =>
                patchBlock(block.id, { line_height: Number(event.target.value) || 1.7 })
              }
            />
          </Stack>
        </Stack>
      );
    case 'image':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>الصورة</SectionLabel>
          <TextField
            size="small"
            fullWidth
            label="رابط الصورة"
            value={block.src}
            onChange={(event) => patchBlock(block.id, { src: event.target.value })}
          />
          <TextField
            size="small"
            fullWidth
            label="نص بديل"
            value={block.alt}
            onChange={(event) => patchBlock(block.id, { alt: event.target.value })}
          />
          <TextField
            size="small"
            fullWidth
            label="رابط النقر (اختياري)"
            value={block.link}
            onChange={(event) => patchBlock(block.id, { link: event.target.value })}
          />
          <Stack direction="row" spacing={0.8}>
            <TextField
              size="small"
              type="number"
              label="العرض"
              value={block.width}
              onChange={(event) => patchBlock(block.id, { width: Number(event.target.value) || 520 })}
            />
            <TextField
              size="small"
              type="number"
              label="استدارة"
              value={block.border_radius}
              onChange={(event) =>
                patchBlock(block.id, { border_radius: Number(event.target.value) || 0 })
              }
            />
          </Stack>
        </Stack>
      );
    case 'button':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>الزر</SectionLabel>
          <TextField
            size="small"
            fullWidth
            label="نص الزر"
            value={block.label}
            onChange={(event) => patchBlock(block.id, { label: event.target.value })}
          />
          <TextField
            size="small"
            fullWidth
            label="رابط الزر"
            value={block.url}
            onChange={(event) => patchBlock(block.id, { url: event.target.value })}
            helperText="استخدم {{tracking_url}} لتتبع النقرات تلقائياً."
          />
          <ColorInput
            label="لون الزر"
            value={block.background_color}
            onChange={(value) => patchBlock(block.id, { background_color: value })}
          />
          <ColorInput
            label="لون نص الزر"
            value={block.text_color}
            onChange={(value) => patchBlock(block.id, { text_color: value })}
          />
          <Stack direction="row" spacing={0.8}>
            <TextField
              size="small"
              type="number"
              label="حجم الخط"
              value={block.font_size}
              onChange={(event) => patchBlock(block.id, { font_size: Number(event.target.value) || 15 })}
            />
            <TextField
              size="small"
              type="number"
              label="استدارة"
              value={block.border_radius}
              onChange={(event) =>
                patchBlock(block.id, { border_radius: Number(event.target.value) || 0 })
              }
            />
          </Stack>
        </Stack>
      );
    case 'divider':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>الفاصل</SectionLabel>
          <ColorInput
            label="لون الفاصل"
            value={block.color}
            onChange={(value) => patchBlock(block.id, { color: value })}
          />
          <Stack direction="row" spacing={0.8}>
            <TextField
              size="small"
              type="number"
              label="السماكة"
              value={block.thickness}
              onChange={(event) =>
                patchBlock(block.id, { thickness: Number(event.target.value) || 1 })
              }
            />
            <TextField
              size="small"
              type="number"
              label="النسبة %"
              value={block.width_percent}
              onChange={(event) =>
                patchBlock(block.id, { width_percent: Number(event.target.value) || 100 })
              }
            />
          </Stack>
        </Stack>
      );
    case 'spacer':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>المسافة</SectionLabel>
          <TextField
            size="small"
            type="number"
            label="الارتفاع (px)"
            value={block.height}
            onChange={(event) => patchBlock(block.id, { height: Number(event.target.value) || 24 })}
          />
        </Stack>
      );
    case 'logo':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>الشعار</SectionLabel>
          <TextField
            size="small"
            type="number"
            label="عرض الشعار"
            value={block.width}
            onChange={(event) => patchBlock(block.id, { width: Number(event.target.value) || 150 })}
          />
          <TextField
            size="small"
            fullWidth
            label="رابط الشعار (اختياري)"
            value={block.link}
            onChange={(event) => patchBlock(block.id, { link: event.target.value })}
          />
          <TextField
            size="small"
            fullWidth
            label="نص بديل"
            value={block.alt}
            onChange={(event) => patchBlock(block.id, { alt: event.target.value })}
          />
          <FormControlLabel
            control={
              <Switch
                checked={block.show_company_name}
                onChange={(event) =>
                  patchBlock(block.id, { show_company_name: event.target.checked })
                }
              />
            }
            label="إظهار اسم الشركة"
          />
        </Stack>
      );
    case 'footer':
      return (
        <Stack spacing={1.1}>
          {common}
          <SectionLabel>التذييل</SectionLabel>
          <TextField
            size="small"
            fullWidth
            multiline
            minRows={2}
            label="نص التذييل"
            value={block.text}
            onChange={(event) => patchBlock(block.id, { text: event.target.value })}
          />
          <Stack direction="row" spacing={0.8}>
            <TextField
              size="small"
              type="number"
              label="حجم الخط"
              value={block.font_size}
              onChange={(event) =>
                patchBlock(block.id, { font_size: Number(event.target.value) || 12 })
              }
            />
            <ColorInput
              label="لون التذييل"
              value={block.color}
              onChange={(value) => patchBlock(block.id, { color: value })}
            />
          </Stack>
          <FormControlLabel
            control={
              <Switch
                checked={block.show_company_name}
                onChange={(event) =>
                  patchBlock(block.id, { show_company_name: event.target.checked })
                }
              />
            }
            label="اسم الشركة"
          />
          <FormControlLabel
            control={
              <Switch
                checked={block.show_support_email}
                onChange={(event) =>
                  patchBlock(block.id, { show_support_email: event.target.checked })
                }
              />
            }
            label="بريد الدعم"
          />
          <FormControlLabel
            control={
              <Switch
                checked={block.show_logo}
                onChange={(event) => patchBlock(block.id, { show_logo: event.target.checked })}
              />
            }
            label="إظهار الشعار"
          />
        </Stack>
      );
    case 'html':
      return (
        <Stack spacing={1.1}>
          {common}
          <Alert severity="warning" sx={{ fontSize: '0.7rem' }}>
            يُسمح بـ HTML البريد الآمن فقط. تتم إزالة السكربتات والأحداث عند الحفظ.
          </Alert>
          <TextField
            multiline
            minRows={8}
            size="small"
            fullWidth
            label="HTML"
            value={block.html}
            onChange={(event) => patchBlock(block.id, { html: event.target.value })}
            InputProps={{ sx: { direction: 'ltr', fontFamily: 'Consolas, monospace', fontSize: '0.75rem' } }}
          />
        </Stack>
      );
    default:
      return null;
  }
}

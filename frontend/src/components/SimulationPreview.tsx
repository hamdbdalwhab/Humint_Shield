/**
 * Channel-specific previews used by the awareness training page.
 *
 * Email keeps its dedicated, pixel-close `SimulatedEmail` component.  QR,
 * vishing and pretexting get their own previews so the teardown always matches
 * the channel the recipient actually experienced.
 */
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { AnimatePresence, motion } from 'framer-motion';
import {
  BadgeCheck,
  Building2,
  FileText,
  FileWarning,
  Folder,
  Gift,
  HardDrive,
  Mic,
  Phone,
  PhoneCall,
  PhoneOff,
  QrCode,
  Send,
  ShieldAlert,
  Usb,
  Video,
  X,
} from 'lucide-react';

import type { RedFlag } from '@/lib/simulationContent';
import type { TrackingContext } from '@/types';

interface PreviewProps {
  context: TrackingContext;
  redFlags: RedFlag[];
  activeFlag: string | null;
  onFlag: (id: string) => void;
  onCloseFlag: () => void;
}

const VISHING_SCRIPT =
  'مرحباً، أنا من الدعم الفني. لقد اكتشفنا فيروساً على جهازك. أحتاج الكود الذي ظهر على شاشتك الآن.';
const PRETEXT_MESSAGE =
  'أنا في اجتماع طارئ. أحتاج منك شراء 5 بطاقات هدايا (100$ لكل بطاقة) وإرسال الأكواد لي الآن. سأعوضك فوراً.';

function brand(context: TrackingContext) {
  return context.brand_primary_color || '#00F0FF';
}

function CompanyMark({ context, size = 38 }: { context: TrackingContext; size?: number }) {
  const primary = brand(context);
  const initial = (context.company_name ?? 'H').trim().slice(0, 1).toUpperCase();
  if (context.brand_logo_url) {
    return (
      <Box
        component="img"
        src={context.brand_logo_url}
        alt={context.company_name ?? 'Company logo'}
        sx={{
          width: size,
          height: size,
          borderRadius: 1.5,
          objectFit: 'contain',
          bgcolor: 'rgba(255,255,255,.94)',
          p: 0.4,
          flex: '0 0 auto',
        }}
      />
    );
  }
  return (
    <Box
      sx={{
        width: size,
        height: size,
        borderRadius: 1.5,
        display: 'grid',
        placeItems: 'center',
        bgcolor: primary,
        color: '#04121c',
        fontWeight: 900,
        flex: '0 0 auto',
      }}
    >
      {initial}
    </Box>
  );
}

function Hotspots({ redFlags, activeFlag, onFlag, onCloseFlag }: PreviewProps) {
  const active = redFlags.find((flag) => flag.id === activeFlag);
  const ActiveIcon = active?.icon;
  return (
    <>
      {redFlags.map((flag) => (
        <Box
          key={flag.id}
          component="button"
          type="button"
          className="mc-flag"
          aria-label={flag.title}
          onClick={() => onFlag(flag.id)}
          sx={{
            position: 'absolute',
            top: flag.top,
            insetInlineStart: flag.left,
            width: { xs: 24, sm: 28 },
            height: { xs: 24, sm: 28 },
            transform: 'translate(-50%, -50%)',
            display: 'grid',
            placeItems: 'center',
            color: '#FF1744',
            bgcolor: 'rgba(255,23,68,.16)',
            border: '1px solid rgba(255,23,68,.58)',
            zIndex: 6,
            cursor: 'pointer',
          }}
        >
          <Box
            component="span"
            sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#FF1744', boxShadow: '0 0 10px #FF1744' }}
          />
        </Box>
      ))}
      <AnimatePresence>
        {active ? (
          <motion.div
            key={active.id}
            initial={{ opacity: 0, y: 8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.97 }}
            transition={{ duration: 0.22 }}
            style={{
              position: 'absolute',
              bottom: 18,
              insetInlineStart: '50%',
              transform: 'translateX(-50%)',
              width: 'min(340px, 90%)',
              zIndex: 8,
            }}
          >
            <Box
              sx={{
                p: 1.5,
                borderRadius: 2,
                bgcolor: 'rgba(11,18,32,.98)',
                border: '1px solid rgba(255,23,68,.42)',
                boxShadow: '0 20px 60px rgba(0,0,0,.55), 0 0 22px rgba(255,23,68,.15)',
                color: 'text.primary',
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.6 }}>
                <Stack direction="row" spacing={0.75} alignItems="center">
                  {ActiveIcon ? <ActiveIcon size={15} color="#FF6B81" /> : null}
                  <Typography sx={{ fontSize: '0.78rem', fontWeight: 800 }}>{active.title}</Typography>
                </Stack>
                <Box
                  component="button"
                  type="button"
                  onClick={onCloseFlag}
                  aria-label="إغلاق"
                  sx={{ border: 0, background: 'transparent', color: 'text.secondary', cursor: 'pointer', p: 0 }}
                >
                  <X size={14} />
                </Box>
              </Stack>
              <Typography sx={{ fontSize: '0.7rem', color: 'text.secondary', lineHeight: 1.7 }}>{active.detail}</Typography>
              <Typography sx={{ fontSize: '0.68rem', color: '#FFC857', mt: 0.8, lineHeight: 1.6 }}>{active.tip}</Typography>
            </Box>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
}

function QrPoster({ context }: { context: TrackingContext }) {
  const primary = brand(context);
  const qr = context.channel_config?.qr;
  return (
    <Box
      dir="rtl"
      sx={{
        position: 'relative',
        borderRadius: 3,
        overflow: 'hidden',
        bgcolor: '#07101e',
        border: '1px solid rgba(255,255,255,.12)',
        boxShadow: '0 30px 80px rgba(0,0,0,.48)',
        p: { xs: 2.2, sm: 3 },
        minHeight: 470,
        background:
          'radial-gradient(circle at 100% 0%, rgba(34,211,238,.16), transparent 42%), linear-gradient(155deg, #0c1729, #060b14)',
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Stack direction="row" spacing={1.1} alignItems="center">
          <CompanyMark context={context} />
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: '0.92rem', lineHeight: 1.3 }}>
              {context.company_name ?? 'شركتك'}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.64rem' }}>
              إشعار أمني داخلي
            </Typography>
          </Box>
        </Stack>
        <Chip
          size="small"
          label="محاكاة تدريبية"
          sx={{ bgcolor: 'rgba(255,255,255,.06)', color: 'text.secondary', fontSize: '0.62rem' }}
        />
      </Stack>

      <Typography sx={{ color: primary, fontWeight: 900, fontSize: '0.72rem', letterSpacing: '.08em', mb: 1 }}>
        {qr?.label || 'تحديث أمني إلزامي'}
      </Typography>
      <Typography sx={{ fontSize: { xs: '1.35rem', sm: '1.65rem' }, fontWeight: 900, lineHeight: 1.45, mb: 1.2 }}>
        {qr?.headline || 'تحديث أمني مطلوب لحسابك'}
      </Typography>
      <Typography sx={{ color: 'text.secondary', fontSize: '0.8rem', lineHeight: 1.9, mb: 2.4 }}>
        {qr?.body ||
          'اكتشف فريق أمن المعلومات نشاطاً غير معتاد على حسابك. امسح رمز الاستجابة السريعة لتأكيد هويتك خلال 24 ساعة.'}
      </Typography>

      <Box
        sx={{
          mx: 'auto',
          width: { xs: 210, sm: 250 },
          p: 1.5,
          borderRadius: 3,
          bgcolor: '#fff',
          boxShadow: `0 0 0 1px ${primary}66, 0 18px 50px rgba(0,0,0,.35)`,
          position: 'relative',
        }}
      >
        <Box
          sx={{
            width: '100%',
            aspectRatio: '1',
            display: 'grid',
            placeItems: 'center',
            borderRadius: 1,
            color: '#07101e',
            backgroundImage:
              'linear-gradient(90deg, #07101e 12%, transparent 12%, transparent 24%, #07101e 24%, #07101e 36%, transparent 36%, transparent 48%, #07101e 48%, #07101e 60%, transparent 60%, transparent 72%, #07101e 72%, #07101e 84%, transparent 84%), linear-gradient(#07101e 12%, transparent 12%, transparent 24%, #07101e 24%, #07101e 36%, transparent 36%, transparent 48%, #07101e 48%, #07101e 60%, transparent 60%, transparent 72%, #07101e 72%, #07101e 84%, transparent 84%)',
            backgroundSize: '16px 16px',
            position: 'relative',
            '&::after': {
              content: '""',
              position: 'absolute',
              inset: '18%',
              bgcolor: '#fff',
              borderRadius: 1,
            },
          }}
        >
          <QrCode size={72} color="#07101e" style={{ position: 'relative', zIndex: 1 }} />
        </Box>
        <Typography sx={{ color: '#07101e', textAlign: 'center', fontWeight: 800, fontSize: '0.68rem', mt: 1 }}>
          امسح الرمز بهاتف العمل
        </Typography>
      </Box>

      <Typography sx={{ textAlign: 'center', color: 'text.secondary', fontSize: '0.7rem', mt: 2 }}>
        {context.first_name ? `${context.first_name}، ` : ''}هذا الإشعار مخصص لك — {context.company_name ?? 'الشركة'}
      </Typography>
      <Typography sx={{ textAlign: 'center', color: 'text.disabled', fontSize: '0.6rem', mt: 0.8 }}>
        لا تُدخل بيانات دخول حقيقية. أبلغ فريق الأمن إذا اشتبهت.
      </Typography>
    </Box>
  );
}

function VishingCall({ context }: { context: TrackingContext }) {
  const primary = brand(context);
  const config = context.channel_config?.vishing;
  const script = config?.script?.trim() || VISHING_SCRIPT;
  const caller = config?.caller_name?.trim() || 'الدعم الفني — تقنية المعلومات';
  return (
    <Box
      dir="rtl"
      sx={{
        position: 'relative',
        mx: 'auto',
        maxWidth: 430,
        minHeight: 560,
        borderRadius: 5,
        overflow: 'hidden',
        color: '#F8FAFC',
        border: '1px solid rgba(255,255,255,.12)',
        boxShadow: '0 35px 100px rgba(0,0,0,.55)',
        background:
          'radial-gradient(circle at 50% 0%, rgba(34,211,238,.14), transparent 46%), linear-gradient(170deg, #0b1424, #050a12 70%)',
        p: 2.2,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ color: 'text.secondary', fontSize: '0.68rem' }}>
        <Stack direction="row" spacing={0.6} alignItems="center">
          <Box className="mc-live-dot" />
          <span>مكالمة جارية</span>
        </Stack>
        <span className="mc-mono">00:42</span>
      </Stack>

      <Stack alignItems="center" spacing={1.2} sx={{ mt: 5 }}>
        <Box
          sx={{
            width: 92,
            height: 92,
            borderRadius: '50%',
            display: 'grid',
            placeItems: 'center',
            bgcolor: 'rgba(255,255,255,.06)',
            border: `1px solid ${primary}55`,
            boxShadow: `0 0 42px ${primary}33`,
          }}
        >
          <PhoneCall size={40} color={primary} />
        </Box>
        <Typography sx={{ fontWeight: 900, fontSize: '1.25rem' }}>{caller}</Typography>
        <Typography sx={{ color: 'text.secondary', fontFamily: 'monospace', fontSize: '0.82rem' }} dir="ltr">
          +966 11 000 0000
        </Typography>
        <Chip size="small" label="رقم غير معروف" sx={{ bgcolor: 'rgba(255,23,68,.10)', color: '#FF8A9A', border: '1px solid rgba(255,23,68,.24)' }} />
      </Stack>

      <Box
        sx={{
          mt: 3,
          p: 1.6,
          borderRadius: 3,
          bgcolor: 'rgba(255,255,255,.04)',
          border: '1px solid rgba(255,255,255,.08)',
        }}
      >
        <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mb: 0.8 }}>
          <Mic size={15} color={primary} />
          <Typography sx={{ fontSize: '0.7rem', color: 'text.secondary', fontWeight: 700 }}>النص المسموع</Typography>
        </Stack>
        <Typography sx={{ fontSize: '0.82rem', lineHeight: 1.95 }}>{script}</Typography>
      </Box>

      <Stack direction="row" spacing={1.2} justifyContent="center" sx={{ mt: 3 }}>
        <Box sx={{ width: 58, height: 58, borderRadius: '50%', display: 'grid', placeItems: 'center', bgcolor: 'rgba(255,23,68,.16)', border: '1px solid rgba(255,23,68,.35)', color: '#FF6B81' }}>
          <PhoneOff size={24} />
        </Box>
        <Box sx={{ width: 58, height: 58, borderRadius: '50%', display: 'grid', placeItems: 'center', bgcolor: 'rgba(0,230,118,.12)', border: '1px solid rgba(0,230,118,.3)', color: '#00E676' }}>
          <Phone size={24} />
        </Box>
      </Stack>
      <Typography sx={{ textAlign: 'center', color: 'text.disabled', fontSize: '0.62rem', mt: 1.4 }}>
        محاكاة تدريبية — لن يتم الاتصال بأي رقم حقيقي
      </Typography>
    </Box>
  );
}

function PretextChat({ context }: { context: TrackingContext }) {
  const primary = brand(context);
  const config = context.channel_config?.pretexting;
  const message = config?.message?.trim() || PRETEXT_MESSAGE;
  const sender = config?.sender_name?.trim() || 'محمد العتيبي';
  return (
    <Box
      dir="rtl"
      sx={{
        position: 'relative',
        maxWidth: 470,
        mx: 'auto',
        borderRadius: 4,
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,.12)',
        boxShadow: '0 35px 100px rgba(0,0,0,.52)',
        bgcolor: '#0b141a',
      }}
    >
      <Box sx={{ px: 1.6, py: 1.2, bgcolor: '#111f2b', borderBottom: '1px solid rgba(255,255,255,.07)' }}>
        <Stack direction="row" spacing={1.1} alignItems="center">
          <Box sx={{ width: 40, height: 40, borderRadius: '50%', display: 'grid', placeItems: 'center', bgcolor: 'rgba(255,255,255,.08)', border: '1px solid rgba(255,255,255,.12)' }}>
            <Building2 size={19} color={primary} />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, fontSize: '0.84rem' }}>{sender}</Typography>
            <Typography variant="caption" sx={{ color: '#25D366', fontSize: '0.64rem' }}>
              متصل الآن · الرئيس التنفيذي
            </Typography>
          </Box>
          <Video size={18} color="#8B9BB4" />
          <Phone size={17} color="#8B9BB4" />
        </Stack>
      </Box>

      <Box
        sx={{
          p: 2,
          minHeight: 340,
          backgroundImage:
            'radial-gradient(circle at 18% 24%, rgba(37,211,102,.035), transparent 30%), radial-gradient(circle at 82% 76%, rgba(0,240,255,.035), transparent 34%)',
        }}
      >
        <Stack alignItems="center" sx={{ mb: 1.5 }}>
          <Chip size="small" label="اليوم" sx={{ bgcolor: 'rgba(255,255,255,.05)', color: 'text.secondary', fontSize: '0.6rem' }} />
        </Stack>
        <Box sx={{ display: 'flex', justifyContent: 'flex-start' }}>
          <Box
            sx={{
              maxWidth: '88%',
              p: 1.3,
              borderRadius: '4px 14px 14px 14px',
              bgcolor: '#1f2c34',
              border: '1px solid rgba(255,255,255,.05)',
            }}
          >
            <Typography sx={{ fontSize: '0.8rem', lineHeight: 1.95 }}>{message}</Typography>
            <Typography sx={{ fontSize: '0.58rem', color: 'rgba(255,255,255,.42)', textAlign: 'left', mt: 0.5 }}>
              09:41 ✓✓
            </Typography>
          </Box>
        </Box>

        <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end' }}>
          <Box sx={{ maxWidth: '72%', p: 1.1, borderRadius: '14px 4px 14px 14px', bgcolor: 'rgba(0,92,75,.55)', border: '1px solid rgba(37,211,102,.18)' }}>
            <Typography sx={{ fontSize: '0.72rem', color: 'rgba(255,255,255,.72)' }}>
              جارٍ تجهيز الأكواد… (هذه محاكاة)
            </Typography>
          </Box>
        </Box>

        <Box sx={{ mt: 2.5, p: 1.1, borderRadius: 2, border: '1px dashed rgba(255,255,255,.12)', bgcolor: 'rgba(255,255,255,.02)' }}>
          <Stack direction="row" spacing={0.8} alignItems="center">
            <Gift size={15} color="#FFC857" />
            <Typography sx={{ fontSize: '0.68rem', color: 'text.secondary' }}>
              طلب شراء 5 بطاقات هدايا × 100$ — إجمالي 500$
            </Typography>
          </Stack>
        </Box>
      </Box>

      <Box sx={{ px: 1.2, py: 1, bgcolor: '#111f2b', borderTop: '1px solid rgba(255,255,255,.07)' }}>
        <Stack direction="row" spacing={0.8} alignItems="center">
          <Box sx={{ flex: 1, py: 0.8, px: 1.2, borderRadius: 99, bgcolor: 'rgba(255,255,255,.06)', color: 'text.disabled', fontSize: '0.7rem' }}>
            اكتب رسالة…
          </Box>
          <Box sx={{ width: 34, height: 34, borderRadius: '50%', display: 'grid', placeItems: 'center', bgcolor: '#25D366', color: '#04121c' }}>
            <Send size={16} />
          </Box>
        </Stack>
      </Box>
      <Box sx={{ px: 1.6, py: 0.7, bgcolor: '#0b141a', display: 'flex', justifyContent: 'center', gap: 0.6, alignItems: 'center' }}>
        <BadgeCheck size={13} color="#8B9BB4" />
        <Typography sx={{ color: 'text.disabled', fontSize: '0.6rem' }}>محاكاة تدريبية — لا ترسل أموالاً أو أكواداً حقيقية</Typography>
      </Box>
    </Box>
  );
}

function UsbDrop({ context }: { context: TrackingContext }) {
  const primary = brand(context);
  const documentName =
    context.channel_config?.usb?.document_name?.trim() || 'راتب_الشهر_القادم.pdf';
  return (
    <Box
      dir="rtl"
      sx={{
        position: 'relative',
        maxWidth: 480,
        mx: 'auto',
        borderRadius: 3,
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,.14)',
        boxShadow: '0 32px 90px rgba(0,0,0,.52)',
        bgcolor: '#0b1220',
        background:
          'radial-gradient(circle at 100% 0%, rgba(0,240,255,.10), transparent 38%), linear-gradient(160deg, #0c1729, #070d18)',
      }}
    >
      {/* Explorer title bar */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ px: 1.4, py: 1, bgcolor: '#111c2e', borderBottom: '1px solid rgba(255,255,255,.08)' }}
      >
        <Stack direction="row" spacing={0.7} alignItems="center">
          <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: '#FF5F57' }} />
          <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: '#FEBC2E' }} />
          <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: '#28C840' }} />
          <Typography sx={{ fontSize: '0.68rem', color: 'text.secondary', ml: 1 }}>
            مستكشف الملفات — USB Drive (E:)
          </Typography>
        </Stack>
        <Chip
          size="small"
          label="محاكاة"
          sx={{ height: 19, bgcolor: 'rgba(255,255,255,.06)', color: 'text.secondary', fontSize: '0.58rem' }}
        />
      </Stack>

      {/* Address bar */}
      <Stack
        direction="row"
        spacing={0.8}
        alignItems="center"
        sx={{ px: 1.5, py: 0.9, borderBottom: '1px solid rgba(255,255,255,.06)', color: 'text.secondary' }}
      >
        <Folder size={14} />
        <Typography dir="ltr" sx={{ fontFamily: 'monospace', fontSize: '0.64rem', color: '#9DB2CE' }}>
          This PC &gt; USB Drive (E:)
        </Typography>
        <Chip
          size="small"
          icon={<Usb size={12} color="#00E676" />}
          label="E: متصل"
          sx={{ ml: 'auto', height: 18, color: '#00E676', bgcolor: 'rgba(0,230,118,.08)', fontSize: '0.54rem' }}
        />
      </Stack>

      <Box sx={{ p: { xs: 1.6, sm: 2 }, minHeight: 410 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.2 }}>
          <Typography sx={{ fontSize: '0.7rem', color: 'text.secondary' }}>
            محتويات الفلاشة — 1 عنصر
          </Typography>
          <Typography sx={{ fontSize: '0.6rem', color: 'text.disabled' }}>
            FAT32 · 14.5 GB متاح
          </Typography>
        </Stack>

        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.2,
            p: 1.2,
            borderRadius: 2,
            bgcolor: 'rgba(0,240,255,.045)',
            border: '1px solid rgba(0,240,255,.16)',
          }}
        >
          <Box
            sx={{
              width: 48,
              height: 58,
              borderRadius: 1.2,
              bgcolor: '#fff',
              color: '#B91C1C',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              flex: '0 0 auto',
              boxShadow: '0 6px 18px rgba(0,0,0,.25)',
            }}
          >
            <FileText size={26} />
            <Typography sx={{ fontSize: '0.48rem', fontWeight: 900, letterSpacing: '.06em' }}>
              PDF
            </Typography>
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, fontSize: '0.82rem', lineHeight: 1.5 }}>
              {documentName}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', fontSize: '0.62rem' }}>
              2.4 MB · آخر تعديل: اليوم 08:12
            </Typography>
          </Box>
          <Chip
            size="small"
            label="تم الفتح"
            sx={{ height: 22, bgcolor: 'rgba(255,176,32,.12)', color: '#FFC857', fontSize: '0.58rem' }}
          />
        </Box>

        <Box
          sx={{
            mt: 1.5,
            p: 1.25,
            borderRadius: 2,
            border: '1px dashed rgba(255,23,68,.38)',
            bgcolor: 'rgba(255,23,68,.055)',
          }}
        >
          <Stack direction="row" spacing={0.9} alignItems="flex-start">
            <ShieldAlert size={17} color="#FF6B81" style={{ flex: '0 0 auto', marginTop: 2 }} />
            <Box>
              <Typography sx={{ fontSize: '0.72rem', fontWeight: 800, color: '#FF8A9A' }}>
                في الهجوم الحقيقي كان هذا الملف قادراً على تدمير جهازك
              </Typography>
              <Typography sx={{ fontSize: '0.64rem', color: 'text.secondary', lineHeight: 1.7, mt: 0.4 }}>
                لم يكن هناك أي تحذير داخلي. أنت الآن ترى نسخة توعوية آمنة، والتحذير
                الحقيقي سيظهر لك بعد فتح الملف.
              </Typography>
            </Box>
          </Stack>
        </Box>

        <Box
          sx={{
            mt: 1.5,
            p: 1.2,
            borderRadius: 2,
            bgcolor: 'rgba(255,255,255,.025)',
            border: '1px solid rgba(255,255,255,.06)',
          }}
        >
          <Stack direction="row" spacing={0.8} alignItems="center">
            <FileWarning size={15} color="#FFC857" />
            <Typography sx={{ fontSize: '0.66rem', color: 'text.secondary', lineHeight: 1.7 }}>
              تحذير: قد يخفي الملف امتداداً ثانياً مثل <span dir="ltr" className="mc-mono">.pdf.exe</span>.
              فعّل إظهار الامتدادات قبل أي فتح.
            </Typography>
          </Stack>
        </Box>

        <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mt: 1.5, color: 'text.disabled' }}>
          <HardDrive size={13} />
          <Typography sx={{ fontSize: '0.6rem' }}>
            هذه نافذة توضيحية — لا توجد فلاشة حقيقية متصلة بهذا المتصفح.
          </Typography>
        </Stack>
      </Box>

      {/* Fake Windows taskbar */}
      <Box
        sx={{
          px: 1.2,
          py: 0.8,
          bgcolor: 'rgba(7,13,24,.92)',
          borderTop: '1px solid rgba(255,255,255,.08)',
          display: 'flex',
          alignItems: 'center',
          gap: 0.9,
        }}
      >
        <Box sx={{ width: 22, height: 22, borderRadius: 0.8, bgcolor: primary, opacity: 0.9 }} />
        <Box sx={{ flex: 1, maxWidth: 170, height: 18, borderRadius: 99, bgcolor: 'rgba(255,255,255,.06)' }} />
        <Usb size={15} color="#8B9BB4" />
        <Typography dir="ltr" sx={{ fontSize: '0.58rem', color: 'text.secondary', ml: 'auto' }}>
          10:42 AM · 10/28/2026
        </Typography>
      </Box>
    </Box>
  );
}

/** Render the preview matching the channel, with clickable red-flag hotspots. */
export function SimulationPreview(props: PreviewProps) {
  const { context, redFlags } = props;
  return (
    <Box sx={{ position: 'relative' }}>
      {context.channel === 'qr' ? <QrPoster context={context} /> : null}
      {context.channel === 'vishing' ? <VishingCall context={context} /> : null}
      {context.channel === 'pretexting' ? <PretextChat context={context} /> : null}
      {context.channel === 'usb' ? <UsbDrop context={context} /> : null}
      <Hotspots {...props} />
      {redFlags.length === 0 ? (
        <Stack direction="row" spacing={0.7} alignItems="center" sx={{ mt: 1.2, color: 'text.disabled' }}>
          <ShieldAlert size={13} />
          <Typography variant="caption">معاينة القناة — لا تُدخل بيانات حقيقية.</Typography>
        </Stack>
      ) : null}
    </Box>
  );
}

export { CompanyMark, PRETEXT_MESSAGE, VISHING_SCRIPT };

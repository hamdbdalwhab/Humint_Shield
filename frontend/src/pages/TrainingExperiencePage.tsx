/**
 * Arabic micro-learning experience shown immediately after a simulated
 * credential submission.
 *
 * The page is public (the tracking UUID is the only credential), fully RTL and
 * built around three moments: a cinematic disclosure, an interactive red-flag
 * teardown of the actual email, and a timed five-question challenge with
 * immediate +1/-1 feedback that unlocks a glowing certificate. Completion is
 * recorded through the real backend; the public page never links to the admin
 * application.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import Divider from '@mui/material/Divider';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import confetti from 'canvas-confetti';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  ArrowLeft,
  AtSign,
  Award,
  BadgeCheck,
  CheckCircle2,
  Clock3,
  Database,
  ExternalLink,
  Flag,
  FolderLock,
  GraduationCap,
  KeyRound,
  Laptop,
  Link2,
  LockKeyhole,
  MailWarning,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Timer,
  X,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { trackingApi } from '@/api/endpoints';
import { ImpactEvidenceCard } from '@/components/ImpactEvidenceCard';
import { SimulationPreview } from '@/components/SimulationPreview';
import { contentForChannel, type ChannelContent } from '@/lib/simulationContent';
import type { TrackingCompleteResponse, TrackingContext } from '@/types';

const COUNTDOWN_SECONDS = 60;

/** English labels displayed beneath the Arabic asset names for clarity. */
const ASSET_ENGLISH: Record<string, string> = {
  'بيانات حساب بريدك الإلكتروني': 'Your Email Account',
  'كلمة مرور بريدك الإلكتروني': 'Your Email Password',
  'الوصول إلى ملفات الموارد البشرية': 'Access to HR Files',
  'الوصول إلى نظام الفواتير والبيانات المالية': 'Access to Billing & Financial Data',
  'الوصول إلى بريد الإدارة التنفيذية': 'Access to Executive Email',
  'الوصول إلى الملفات المشتركة': 'Access to Shared Files',
  'الوصول إلى شبكة الشركة عبر VPN': 'Access to Corporate VPN',
  'الوصول إلى الأنظمة الداخلية المتاحة من حسابك': 'Access to Internal Systems',
  'جلسة دخول دائمة (تذكرني)': 'Persistent Login Session',
  'بيانات القسم ومكان العمل': 'Department & Office Details',
  'بيانات الدخول إلى بوابة الشركة': 'Corporate Portal Credentials',
  'جلسة دخول دائمة على جهازك': 'Persistent Session on Your Device',
  'رمز التحقق لمرة واحدة (OTP)': 'One-Time Verification Code (OTP)',
  'الوصول إلى حساب الدعم الفني': 'Access to the IT Support Account',
  'محاولة إعادة تعيين كلمة المرور': 'Password Reset Attempt',
  'أموال الشركة عبر بطاقات الهدايا': 'Company Funds via Gift Cards',
  'أكواد البطاقات — نقد فوري للمهاجم': 'Gift Card Codes — Instant Cash',
  'ثقة العلاقة مع الإدارة التنفيذية': 'Trust in Executive Communications',
  'التحكم الكامل في جهاز العمل': 'Full Control of the Work Device',
  'ملفات العمل المخزنة على القرص': 'Work Files Stored on Disk',
  'بيانات الدخول المحفوظة في المتصفح': 'Credentials Saved in the Browser',
  'جلسة الشبكة الداخلية للشركة': 'Internal Corporate Network Session',
};

function assetIcon(asset: string) {
  if (asset.includes('كلمة مرور')) return KeyRound;
  if (asset.includes('جهاز') || asset.includes('التحكم')) return Laptop;
  if (asset.includes('ملفات') || asset.includes('الملفات')) return FolderLock;
  if (asset.includes('بريد')) return MailWarning;
  return Database;
}

interface RedFlag {
  id: string;
  title: string;
  detail: string;
  tip: string;
  icon: typeof AtSign;
  top: string;
  left: string;
}

const RED_FLAGS: RedFlag[] = [
  {
    id: 'sender',
    title: 'المرسل ليس من نطاق شركتك',
    detail:
      'عنوان المرسل يستخدم نطاقاً مشابهاً (micros0ft-365.com) وليس النطاق الرسمي للشركة. attackers يشترون نطاقات تبدو صحيحة للعين السريعة.',
    tip: 'اقرأ النطاق بعد علامة @ حرفاً بحرف، ولا تثق بالاسم الظاهر فقط.',
    icon: AtSign,
    top: '13%',
    left: '15%',
  },
  {
    id: 'urgency',
    title: 'لغة استعجال وتهديد',
    detail:
      'عبارات مثل «خلال 24 ساعة»، «سيُقفل حسابك»، و«إجراء فوري» مصممة لتعطيل تفكيرك ودفعك للتصرف بسرعة.',
    tip: 'الاستعجال غير المتوقع هو علامة خطر. توقف، تنفّس، وتحقّق من قناة أخرى.',
    icon: Clock3,
    top: '33%',
    left: '63%',
  },
  {
    id: 'credentials',
    title: 'طلب إدخال بيانات حساسة',
    detail:
      'خدمة شرعية لا تطلب منك إعادة إدخال كلمة المرور أو تأكيد بياناتك البنكية عبر رابط في بريد إلكتروني.',
    tip: 'افتح الموقع الرسمي مباشرة من المتصفح، لا من رابط داخل الرسالة.',
    icon: LockKeyhole,
    top: '57%',
    left: '11%',
  },
  {
    id: 'link',
    title: 'الرابط يقود إلى وجهة مختلفة',
    detail:
      'نص الزر يوحي بأنه موقع الشركة، لكن الوجهة الفعلية نطاق خارجي. مرّر المؤشر فوق الرابط واقرأ العنوان الكامل قبل النقر.',
    tip: 'لا تنقر. اكتب عنوان الموقع بنفسك أو استخدم الإشارة المرجعية المحفوظة.',
    icon: Link2,
    top: '80%',
    left: '10%',
  },
];

interface QuizOption {
  id: string;
  text: string;
}

interface QuizQuestion {
  id: string;
  prompt: string;
  options: QuizOption[];
  correct: string;
  explanation: string;
  wrongHint: string;
}

const QUIZ_QUESTIONS: QuizQuestion[] = [
  {
    id: 'sender',
    prompt: 'ما أقوى مؤشر على أن هذه الرسالة مشبوهة؟',
    options: [
      { id: 'logo', text: 'وجود شعار الشركة الصحيح داخل الرسالة' },
      { id: 'domain', text: 'الرابط والمرسل يستخدمان نطاقاً مختلفاً عن نطاق الشركة' },
      { id: 'language', text: 'الرسالة مكتوبة باللغة الإنجليزية' },
    ],
    correct: 'domain',
    explanation:
      'صحيح. التحقق من النطاق الفعلي — لا من النص الظاهر — هو أقوى مؤشر واحد على التصيّد.',
    wrongHint: 'الشعار واللغة قابلان للتقليد بسهولة. ابحث عن النطاق الفعلي للمرسل والرابط.',
  },
  {
    id: 'urgency',
    prompt: 'رسالة من «الدعم الفني» تهدد بإغلاق حسابك خلال 24 ساعة. ما الذي يجب أن تلاحظه؟',
    options: [
      { id: 'deadline', text: 'أن المهلة قصيرة جداً وتخلق ضغطاً نفسياً' },
      { id: 'signature', text: 'أن الرسالة تحتوي على توقيع إلكتروني' },
      { id: 'format', text: 'أن الرسالة تستخدم خطاً رسمياً' },
    ],
    correct: 'deadline',
    explanation:
      'صحيح. الاستعجال والتهديد بالإغلاق أسلوب ضغط شائع لدفعك إلى التصرف قبل التفكير.',
    wrongHint: 'التوقيع والخط ليسا دليلاً على الشرعية. لاحظ الضغط الزمني غير الطبيعي.',
  },
  {
    id: 'credentials',
    prompt: 'أي طلب داخل بريد إلكتروني يجب أن يجعلك تتوقف فوراً؟',
    options: [
      { id: 'meeting', text: 'دعوة لحضور اجتماع فريق الأسبوع القادم' },
      { id: 'newsletter', text: 'إشعار بإصدار نشرة داخلية جديدة' },
      { id: 'password', text: 'إعادة إدخال كلمة المرور عبر رابط داخل الرسالة' },
    ],
    correct: 'password',
    explanation:
      'صحيح. الخدمات الشرعية لا تطلب كلمة المرور عبر رابط في بريد. افتح الموقع الرسمي مباشرة.',
    wrongHint: 'الاجتماعات والنشرات لا تحتاج بيانات دخول. ركّز على طلبات كلمة المرور أو البيانات الحساسة.',
  },
  {
    id: 'link',
    prompt: 'قبل النقر على أي رابط في رسالة، ما الإجراء الصحيح؟',
    options: [
      { id: 'text', text: 'الاعتماد على النص الظاهر للرابط فقط' },
      { id: 'destination', text: 'فحص الوجهة الفعلية للرابط بعد تمرير المؤشر فوقه' },
      { id: 'color', text: 'التأكد من أن لون الزر أزرق مثل المواقع الرسمية' },
    ],
    correct: 'destination',
    explanation:
      'صحيح. النص الظاهر يمكن تزويره؛ الوجهة الفعلية هي ما يهم. والأفضل فتح الموقع مباشرة من المتصفح.',
    wrongHint: 'النص واللون يمكن تقليدهما. مرّر المؤشر واقرأ العنوان الكامل، أو افتح الموقع يدوياً.',
  },
  {
    id: 'report',
    prompt: 'إذا شككت في رسالة، ما أفضل تصرف؟',
    options: [
      { id: 'forward', text: 'إعادة توجيهها إلى زميل ليسأل عنها' },
      { id: 'report', text: 'الإبلاغ عنها لفريق الأمن عبر القناة الرسمية دون النقر' },
      { id: 'delete', text: 'حذفها فقط دون إخبار أحد' },
    ],
    correct: 'report',
    explanation:
      'صحيح. الإبلاغ عبر القناة الرسمية يحمي زملاءك ويمنح فريق الأمن فرصة الاحتواء السريع.',
    wrongHint: 'إعادة التوجيه قد تنشر الرسالة، والحذف وحده لا يحمي الآخرين. أبلغ فريق الأمن.',
  },
];

const EMAIL_CONTENT: ChannelContent = {
  key: 'email',
  label: 'تصيّد بالبريد الإلكتروني',
  chip: 'Email phishing',
  headline: 'لقد وقعت في اختبار أمني، لا تقلق.',
  description:
    'هذه محاكاة توعية مصرّح بها من مؤسستك. خذ دقيقة لتتعرّف على مؤشرات الرسالة المشبوهة قبل أن تصل رسالة حقيقية.',
  previewKind: 'email',
  redFlags: RED_FLAGS,
  quiz: QUIZ_QUESTIONS,
};

function fireConfetti() {
  const colors = ['#00F0FF', '#7000FF', '#00E676', '#FFB020', '#E2E8F0'];
  confetti({ particleCount: 140, spread: 78, origin: { y: 0.66 }, colors, zIndex: 9999 });
  window.setTimeout(() => {
    confetti({ particleCount: 90, angle: 60, spread: 65, origin: { x: 0, y: 0.7 }, colors, zIndex: 9999 });
    confetti({ particleCount: 90, angle: 120, spread: 65, origin: { x: 1, y: 0.7 }, colors, zIndex: 9999 });
  }, 220);
}

function InvalidTraining() {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 2 }}>
      <Box
        sx={{
          width: '100%',
          maxWidth: 470,
          p: 4,
          borderRadius: 4,
          textAlign: 'center',
          bgcolor: 'rgba(21,30,50,.82)',
          border: '1px solid rgba(255,23,68,.25)',
          boxShadow: '0 30px 90px rgba(0,0,0,.55)',
        }}
      >
        <ShieldAlert size={44} color="#FF1744" />
        <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, mt: 2, mb: 1 }}>
          جلسة التدريب غير صالحة
        </Typography>
        <Typography variant="body2" color="text.secondary">
          تعذّر العثور على جلسة المحاكاة. اطلب من فريق الأمن رابطاً جديداً، ولا تُدخل بياناتك
          في أي رابط لا تثق به.
        </Typography>
      </Box>
    </Box>
  );
}

function MicrosoftMark() {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '9px 9px', gap: '2px', width: 20, height: 20 }}>
      <Box sx={{ bgcolor: '#f25022' }} />
      <Box sx={{ bgcolor: '#7fba00' }} />
      <Box sx={{ bgcolor: '#00a4ef' }} />
      <Box sx={{ bgcolor: '#ffb900' }} />
    </Box>
  );
}

function SimulatedEmail({
  context,
  activeFlag,
  onFlag,
  onCloseFlag,
}: {
  context: TrackingContext;
  activeFlag: string | null;
  onFlag: (id: string) => void;
  onCloseFlag: () => void;
}) {
  const template = (context.template_name ?? '').toLowerCase();
  const isMicrosoft = template.includes('microsoft') || template.includes('password');
  const isHr = template.includes('hr') || template.includes('records');
  const isCeo = template.includes('ceo') || template.includes('brief');
  const isInvoice = template.includes('invoice');
  const active = RED_FLAGS.find((flag) => flag.id === activeFlag);
  const ActiveIcon = active?.icon;

  const senderEmail = isMicrosoft
    ? 'no-reply@micros0ft-365.com'
    : isHr
      ? 'hr-portal@company-benefits.net'
      : isCeo
        ? 'ceo.office@company-exec.net'
        : isInvoice
          ? 'billing@northstar-supply.example'
          : 'drive-share@google-docs.net';

  return (
    <Box
      sx={{
        borderRadius: 3,
        border: '1px solid rgba(255,255,255,.12)',
        bgcolor: '#f3f4f6',
        overflow: 'hidden',
        boxShadow: '0 30px 80px rgba(0,0,0,.45)',
        position: 'relative',
      }}
    >
      <Box
        sx={{
          px: 2,
          py: 1.2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          bgcolor: 'rgba(10,15,28,.94)',
          borderBottom: '1px solid rgba(255,255,255,.08)',
        }}
      >
        <Stack direction="row" spacing={0.75} alignItems="center">
          <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#FF5F57' }} />
          <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#FEBC2E' }} />
          <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#28C840' }} />
        </Stack>
        <Typography sx={{ color: '#8B9BB4', fontSize: '0.66rem', letterSpacing: '.08em' }}>
          INBOX · MESSAGE PREVIEW
        </Typography>
        <MailWarning size={14} color="#FF6B81" />
      </Box>

      <Box dir="ltr" sx={{ p: { xs: 1.5, sm: 2.2 }, position: 'relative', bgcolor: '#fff' }}>
        <Stack direction="row" spacing={1.2} alignItems="flex-start" sx={{ mb: 1.8 }}>
          <Box
            sx={{
              width: 38,
              height: 38,
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              bgcolor: isMicrosoft ? '#e8f2fb' : isHr ? '#e8eef5' : '#f1f3f4',
              border: '1px solid rgba(0,0,0,.08)',
              flex: '0 0 auto',
            }}
          >
            {isMicrosoft ? <MicrosoftMark /> : <Typography sx={{ fontWeight: 800, color: '#12324f', fontSize: '0.8rem' }}>{(context.company_name ?? 'C').slice(0, 1)}</Typography>}
          </Box>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="baseline">
              <Typography sx={{ fontFamily: 'Arial, sans-serif', fontSize: '0.82rem', fontWeight: 700, color: '#202124' }}>
                {context.sender_name ?? 'IT Service Desk'}{' '}
                <Box component="span" sx={{ fontWeight: 400, color: '#5f6368', fontSize: '0.76rem' }}>
                  &lt;{senderEmail}&gt;
                </Box>
              </Typography>
              <Typography sx={{ fontFamily: 'Arial, sans-serif', fontSize: '0.7rem', color: '#80868b' }}>09:14</Typography>
            </Stack>
            <Typography sx={{ fontFamily: 'Arial, sans-serif', fontSize: '0.71rem', color: '#5f6368' }}>
              to {context.email ?? 'you'} · External sender
            </Typography>
          </Box>
        </Stack>

        <Divider sx={{ borderColor: '#e0e0e0', mb: 1.6 }} />

        <Typography
          sx={{
            fontFamily: 'Arial, sans-serif',
            fontSize: { xs: '0.98rem', sm: '1.08rem' },
            fontWeight: 700,
            color: '#202124',
            mb: 1.6,
            lineHeight: 1.4,
          }}
        >
          {context.subject ?? 'Action required: verify your account'}
        </Typography>

        {isMicrosoft ? (
          <Box sx={{ fontFamily: 'Arial, sans-serif', color: '#242424', fontSize: '0.78rem', lineHeight: 1.7 }}>
            <Typography sx={{ fontSize: '0.8rem', mb: 1 }}>Hi {context.first_name ?? 'there'},</Typography>
            <Typography sx={{ fontSize: '0.8rem', mb: 1.2 }}>
              Your Microsoft 365 password expires <strong>today at 11:59 PM</strong>. To keep
              access to your mailbox, you must confirm your identity within the next 24 hours.
            </Typography>
            <Box sx={{ border: '1px solid #edebe9', borderRadius: 1, p: 1.1, mb: 1.4, bgcolor: '#faf9f8' }}>
              <div><span style={{ color: '#605e5c' }}>Account:</span> <strong>{context.email}</strong></div>
              <div><span style={{ color: '#605e5c' }}>Deadline:</span> Today, 11:59 PM</div>
              <div><span style={{ color: '#605e5c' }}>Reference:</span> SEC-2026-4471</div>
            </Box>
            <Box component="span" sx={{ display: 'inline-block', px: 2.2, py: 1, bgcolor: '#0078d4', color: '#fff', borderRadius: 0.5, fontWeight: 700, fontSize: '0.76rem' }}>
              Change password now
            </Box>
            <Typography sx={{ fontSize: '0.68rem', color: '#8a8886', mt: 1.4 }}>
              If you do not act, your mailbox will be switched to read-only and you will be signed out of all devices.
            </Typography>
          </Box>
        ) : isHr ? (
          <Box sx={{ fontFamily: 'Arial, sans-serif', color: '#243b53', fontSize: '0.78rem', lineHeight: 1.7 }}>
            <Typography sx={{ fontSize: '0.8rem', mb: 1 }}>Dear {context.first_name ?? 'employee'},</Typography>
            <Typography sx={{ fontSize: '0.8rem', mb: 1.2 }}>
              As part of the annual compliance review, every employee must confirm their personal
              and payroll information before <strong>Friday, 5:00 PM</strong>. Unconfirmed records
              may delay payroll processing.
            </Typography>
            <Box sx={{ bgcolor: '#f7f9fc', border: '1px solid #e3e8ee', p: 1.2, mb: 1.4, fontSize: '0.73rem', color: '#486581' }}>
              Home address and emergency contact<br />Bank account and payroll details<br />Tax residency declaration
            </Box>
            <Box component="span" sx={{ display: 'inline-block', px: 2.2, py: 1, bgcolor: '#12324f', color: '#fff', fontWeight: 700, fontSize: '0.76rem' }}>
              Open employee portal
            </Box>
          </Box>
        ) : isCeo ? (
          <Box sx={{ fontFamily: 'Arial, sans-serif', color: '#222', fontSize: '0.8rem', lineHeight: 1.8 }}>
            <Typography sx={{ fontSize: '0.8rem', mb: 1 }}>{context.first_name ?? 'there'},</Typography>
            <Typography sx={{ fontSize: '0.8rem', mb: 1.2 }}>
              I need five minutes of your attention before the board briefing today. Review the
              confidential note I shared. It covers the acquisition timeline and the two names we discussed.
              Please do not forward it.
            </Typography>
            <Box component="span" sx={{ display: 'inline-block', px: 2.2, py: 1, bgcolor: '#111', color: '#fff', fontWeight: 600, fontSize: '0.76rem' }}>
              Open secure brief
            </Box>
            <Typography sx={{ fontSize: '0.7rem', color: '#999', mt: 1.5 }}>Sent from my iPhone</Typography>
          </Box>
        ) : isInvoice ? (
          <Box sx={{ fontFamily: 'Arial, sans-serif', color: '#243b53', fontSize: '0.78rem', lineHeight: 1.7 }}>
            <Box sx={{ bgcolor: '#0d2137', color: '#fff', p: 1.4, mb: 1.4 }}>
              <div style={{ fontWeight: 700, letterSpacing: 1 }}>NORTHSTAR SUPPLY</div>
              <div style={{ fontSize: 10, color: '#8fb3d9' }}>INVOICE · INV-2026-8841</div>
            </Box>
            <Typography sx={{ fontSize: '0.8rem', mb: 1.1 }}>
              Payment is now <strong>5 days overdue</strong>. A late-payment fee may be applied if the
              balance is not settled within 48 hours.
            </Typography>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, marginBottom: 12 }}>
              <tbody>
                <tr style={{ background: '#f0f4f8' }}><td style={{ padding: 6 }}>Enterprise network hardware</td><td align="right" style={{ padding: 6 }}>$11,940.00</td></tr>
                <tr><td style={{ padding: 6, borderTop: '1px solid #edf1f5' }}>Managed switch licensing</td><td align="right" style={{ padding: 6, borderTop: '1px solid #edf1f5' }}>$4,800.00</td></tr>
                <tr><td style={{ padding: 6, borderTop: '1px solid #edf1f5', fontWeight: 700 }}>TOTAL DUE</td><td align="right" style={{ padding: 6, borderTop: '1px solid #edf1f5', fontWeight: 700 }}>$18,420.00</td></tr>
              </tbody>
            </table>
            <Box component="span" sx={{ display: 'inline-block', px: 2.2, py: 1, bgcolor: '#0d2137', color: '#fff', fontWeight: 700, fontSize: '0.76rem' }}>
              Review invoice
            </Box>
          </Box>
        ) : (
          <Box sx={{ fontFamily: 'Arial, sans-serif', color: '#202124', fontSize: '0.78rem', lineHeight: 1.7 }}>
            <Typography sx={{ fontSize: '0.8rem', mb: 1 }}>{context.first_name ?? 'there'},</Typography>
            <Typography sx={{ fontSize: '0.8rem', mb: 1.2 }}>
              A file was shared with you by a colleague at {context.company_name ?? 'your company'}.
            </Typography>
            <Box sx={{ border: '1px solid #dadce0', borderRadius: 1.5, p: 1.4, mb: 1.4 }}>
              <div style={{ fontWeight: 700 }}>Q4 strategy review — final.pptx</div>
              <div style={{ fontSize: 11, color: '#5f6368' }}>Shared by your manager · 4.8 MB · comment access</div>
            </Box>
            <Box component="span" sx={{ display: 'inline-block', px: 2.2, py: 1, bgcolor: '#1a73e8', color: '#fff', fontWeight: 600, fontSize: '0.76rem', borderRadius: 0.5 }}>
              Open document
            </Box>
          </Box>
        )}

        {/* Hotspots are positioned over the areas described in the debrief. */}
        {RED_FLAGS.map((flag) => (
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
              bgcolor: 'rgba(255,23,68,.14)',
              border: '1px solid rgba(255,23,68,.55)',
              zIndex: 3,
            }}
          >
            <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#FF1744', boxShadow: '0 0 10px #FF1744' }} />
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
                top: '72%',
                insetInlineStart: '50%',
                transform: 'translateX(-50%)',
                width: 'min(310px, 88%)',
                zIndex: 5,
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
                  <Box component="button" type="button" onClick={onCloseFlag} aria-label="إغلاق" sx={{ border: 0, background: 'transparent', color: 'text.secondary', cursor: 'pointer', p: 0 }}>
                    <X size={14} />
                  </Box>
                </Stack>
                <Typography sx={{ fontSize: '0.7rem', color: 'text.secondary', lineHeight: 1.7 }}>{active.detail}</Typography>
                <Typography sx={{ fontSize: '0.68rem', color: '#FFC857', mt: 0.8, lineHeight: 1.6 }}>{active.tip}</Typography>
              </Box>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </Box>
    </Box>
  );
}

function CountdownRing({ remaining }: { remaining: number }) {
  const radius = 72;
  const circumference = 2 * Math.PI * radius;
  const progress = (COUNTDOWN_SECONDS - remaining) / COUNTDOWN_SECONDS;
  const ready = remaining <= 0;
  const color = ready ? '#00E676' : '#00F0FF';

  return (
    <Box sx={{ position: 'relative', width: 176, height: 176, mx: 'auto' }}>
      <svg width="176" height="176" viewBox="0 0 176 176" style={{ transform: 'rotate(-90deg)' }}>
        <defs>
          <linearGradient id="timer-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={color} />
            <stop offset="100%" stopColor="#7000FF" />
          </linearGradient>
        </defs>
        <circle cx="88" cy="88" r={radius} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth="10" />
        <circle
          cx="88"
          cy="88"
          r={radius}
          fill="none"
          stroke="url(#timer-gradient)"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - progress)}
          style={{ transition: 'stroke-dashoffset 1s linear, stroke .3s ease', filter: `drop-shadow(0 0 8px ${color}66)` }}
        />
      </svg>
      <Stack sx={{ position: 'absolute', inset: 0 }} alignItems="center" justifyContent="center" spacing={0.25}>
        {ready ? <ShieldCheck size={30} color="#00E676" /> : <Timer size={24} color="#00F0FF" />}
        <Typography sx={{ fontSize: '2.2rem', fontWeight: 800, lineHeight: 1, color: ready ? 'success.main' : 'text.primary' }}>
          {ready ? 'جاهز' : remaining}
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem' }}>
          {ready ? 'أكملت وقت القراءة' : 'ثانية متبقية'}
        </Typography>
      </Stack>
    </Box>
  );
}

function SessionEnded({ displayName }: { displayName: string }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 2 }}>
      <Box
        sx={{
          width: '100%',
          maxWidth: 560,
          p: { xs: 3, sm: 5 },
          borderRadius: 5,
          textAlign: 'center',
          bgcolor: 'rgba(21,30,50,.88)',
          border: '1px solid rgba(0,230,118,.26)',
          boxShadow: '0 30px 90px rgba(0,0,0,.55), 0 0 40px rgba(0,230,118,.08)',
        }}
      >
        <Box
          sx={{
            width: 72,
            height: 72,
            mx: 'auto',
            borderRadius: '50%',
            display: 'grid',
            placeItems: 'center',
            color: '#031018',
            background: 'linear-gradient(135deg, #00F0FF, #7CFFB2)',
            boxShadow: '0 0 44px rgba(0,240,255,.32)',
          }}
        >
          <ShieldCheck size={36} />
        </Box>
        <Typography sx={{ fontSize: '1.5rem', fontWeight: 800, mt: 2.5, mb: 1 }}>
          شكراً لك، {displayName}
        </Typography>
        <Typography sx={{ color: 'text.secondary', lineHeight: 1.9 }}>
          تم إنهاء جلسة التدريب بنجاح. لم يعد لهذه الصفحة أي وصول إلى لوحة الإدارة.
          يمكنك إغلاق التبويب الآن والعودة إلى عملك بأمان.
        </Typography>
      </Box>
    </Box>
  );
}

export function TrainingExperiencePage() {
  const { trackingUuid } = useParams<{ trackingUuid: string }>();
  const [searchParams] = useSearchParams();
  const [remaining, setRemaining] = useState(COUNTDOWN_SECONDS);
  const [activeFlag, setActiveFlag] = useState<string | null>(null);
  const [discovered, setDiscovered] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [completion, setCompletion] = useState<TrackingCompleteResponse | null>(null);
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);
  const [reported, setReported] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const certificateRef = useRef<HTMLDivElement | null>(null);
  const confettiFired = useRef(false);

  const contextQuery = useQuery({
    queryKey: ['training-context', trackingUuid],
    queryFn: () => trackingApi.context(trackingUuid as string),
    enabled: Boolean(trackingUuid),
    staleTime: 60_000,
    retry: 1,
  });

  const context = contextQuery.data;
  const isOtpWarning =
    searchParams.get('mfa') === 'true' ||
    searchParams.get('otp') === 'true' ||
    Boolean(context?.otp_submitted);
  const isQrChannel =
    searchParams.get('channel') === 'qr' ||
    (context?.channel || '').toLowerCase() === 'qr';
  const content = isQrChannel
    ? contentForChannel('qr')
    : context && context.channel && context.channel !== 'email'
      ? contentForChannel(context.channel)
      : EMAIL_CONTENT;
  const compromisedAssets = context?.compromised_assets ?? [];
  const alreadyComplete = Boolean(context?.already_completed);
  const completed = alreadyComplete || Boolean(completion?.success);
  const ready = remaining <= 0;

  // Opening the training page is itself an interaction: record it once so the
  // monitoring board shows that the recipient followed the warning link, and not
  // only when the quiz is completed.  A failed call is retried on the next mount.
  const visitRecorded = useRef(false);
  useEffect(() => {
    if (!trackingUuid || visitRecorded.current) return;
    visitRecorded.current = true;
    void trackingApi.formViewed(trackingUuid).catch(() => {
      visitRecorded.current = false;
    });
  }, [trackingUuid]);

  useEffect(() => {
    if (remaining <= 0) return undefined;
    const handle = window.setTimeout(() => {
      setRemaining((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearTimeout(handle);
  }, [remaining]);

  useEffect(() => {
    if (!completed || confettiFired.current) return;
    confettiFired.current = true;
    fireConfetti();
  }, [completed]);

  useEffect(() => {
    if (!completed) return;
    window.setTimeout(() => {
      certificateRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 250);
  }, [completed]);

  const discover = useCallback((id: string) => {
    setActiveFlag((current) => (current === id ? null : id));
    setDiscovered((current) => (current.includes(id) ? current : [...current, id]));
  }, []);

  const selectAnswer = useCallback(
    (questionId: string, optionId: string) => {
      if (!ready) return;
      setAnswers((current) =>
        current[questionId] ? current : { ...current, [questionId]: optionId },
      );
    },
    [ready],
  );

  const answeredCount = Object.keys(answers).length;
  const quizComplete = answeredCount === content.quiz.length;
  const quizScore = useMemo(
    () =>
      content.quiz.reduce(
        (total, question) =>
          total + (answers[question.id] === question.correct ? 1 : 0),
        0,
      ),
    [answers, content.quiz],
  );

  const completeTraining = useCallback(async () => {
    if (!trackingUuid || completing || !ready || !quizComplete) return;
    setCompleting(true);
    setCompleteError(null);
    try {
      const result = await trackingApi.complete(trackingUuid, {
        score: quizScore,
        total: content.quiz.length,
      });
      setCompletion(result);
      if (!result.success) {
        setCompleteError(result.message || 'تعذّر تسجيل الإكمال. حاول مرة أخرى.');
      }
    } catch {
      setCompleteError('تعذّر الاتصال بالخادم. تحقّق من الشبكة ثم أعد المحاولة.');
    } finally {
      setCompleting(false);
    }
  }, [completing, content.quiz.length, quizComplete, quizScore, ready, trackingUuid]);

  const reportPhishing = useCallback(async () => {
    if (!trackingUuid || reportBusy) return;
    setReportBusy(true);
    try {
      await trackingApi.report(trackingUuid);
      setReported(true);
    } catch {
      setReported(false);
    } finally {
      setReportBusy(false);
    }
  }, [reportBusy, trackingUuid]);

  const progress = useMemo(
    () => (discovered.length / content.redFlags.length) * 100,
    [discovered.length, content.redFlags.length],
  );

  if (contextQuery.isLoading) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Stack alignItems="center" spacing={2}>
          <Box className="mc-live-dot" />
          <Typography variant="body2" color="text.secondary">
            جارٍ تحميل جلسة التدريب…
          </Typography>
        </Stack>
      </Box>
    );
  }

  if (!trackingUuid || contextQuery.error || !context) return <InvalidTraining />;

  const displayName = [context.first_name, context.last_name].filter(Boolean).join(' ') || context.email || 'الموظف';
  const finalScore = completion?.quiz_score ?? context.quiz_score ?? (alreadyComplete ? null : quizScore);
  const finalTotal = completion?.quiz_total ?? context.quiz_total ?? content.quiz.length;

  if (sessionEnded) return <SessionEnded displayName={displayName} />;

  return (
    <Box sx={{ minHeight: '100vh', position: 'relative', overflow: 'hidden', pb: 8 }}>
      <Box className="mc-aurora" />
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          backgroundImage:
            'linear-gradient(rgba(0,240,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(0,240,255,.025) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
          maskImage: 'radial-gradient(circle at 50% 20%, black, transparent 70%)',
        }}
      />
      {Array.from({ length: 16 }).map((_, index) => (
        <Box
          key={index}
          className="mc-particle"
          sx={{
            left: `${(index * 6.4 + 3) % 100}%`,
            bottom: `${(index * 11) % 60}%`,
            animationDelay: `${index * 0.7}s`,
            animationDuration: `${10 + (index % 5) * 2}s`,
            bgcolor: index % 3 === 0 ? '#B388FF' : '#00F0FF',
          }}
        />
      ))}

      <Container maxWidth="lg" sx={{ position: 'relative', zIndex: 1, pt: { xs: 5, sm: 7, md: 9 } }}>
        {/* ------------------------------ hero ------------------------------ */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          <Stack alignItems="center" textAlign="center" spacing={2} sx={{ mb: { xs: 4, md: 5.5 } }}>
            <Chip
              icon={<GraduationCap size={15} />}
              label={`🎓 ${content.chip}`}
              color="primary"
              variant="outlined"
              sx={{ px: 0.5, py: 0.4, fontSize: '0.78rem', fontWeight: 800 }}
            />
            <Typography
              component="h1"
              sx={{
                fontSize: { xs: '1.85rem', sm: '2.5rem', md: '3.1rem' },
                fontWeight: 800,
                lineHeight: 1.35,
                letterSpacing: '-.03em',
                maxWidth: 960,
              }}
            >
              <Box component="span" className="mc-neon-text">
                {content.headline}
              </Box>
            </Typography>
            <Typography sx={{ color: 'text.secondary', maxWidth: 760, fontSize: { xs: '0.9rem', md: '1rem' }, lineHeight: 1.9 }}>
              {content.description} هذه محاكاة توعية مصرّح بها من {context?.company_name ?? 'مؤسستك'}؛
              لم تُرسل بياناتك إلى أي جهة خارجية.
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.75, justifyContent: 'center' }}>
              <Chip size="small" icon={<ShieldCheck size={13} />} label="لا ضرر عليك" color="success" variant="outlined" />
              <Chip size="small" icon={<Clock3 size={13} />} label="60 ثانية" color="info" variant="outlined" />
              <Chip size="small" icon={<Award size={13} />} label="+5 نقاط مناعة" color="primary" variant="outlined" />
            </Stack>
          </Stack>
        </motion.div>

        {/* --------------------- QR / Quishing Warning Card --------------------- */}
        {isQrChannel && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.08 }}
          >
            <Alert
              severity="error"
              icon={<ShieldAlert size={28} color="#FF3D71" />}
              sx={{
                mb: { xs: 3, md: 4 },
                p: { xs: 2, sm: 2.6 },
                borderRadius: 3.5,
                bgcolor: 'rgba(255, 61, 113, 0.12)',
                border: '1.5px solid rgba(255, 61, 113, 0.45)',
                color: '#FFD6E0',
                boxShadow: '0 12px 40px rgba(255, 61, 113, 0.15)',
                alignItems: 'center',
                '& .MuiAlert-icon': { alignItems: 'center' },
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: { xs: '1rem', sm: '1.14rem' }, lineHeight: 1.6 }}>
                تنبيه أمني عالي الخطورة: لا تقم أبداً بمسح رموز QR غير الموثوقة أو إدخال بيانات الدخول من خلالها.
              </Typography>
            </Alert>
          </motion.div>
        )}
        {/* --------------------- OTP / 2FA Warning Card --------------------- */}
        {isOtpWarning && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.08 }}
          >
            <Alert
              severity="warning"
              icon={<ShieldAlert size={28} color="#FF9100" />}
              sx={{
                mb: { xs: 3, md: 4 },
                p: { xs: 2, sm: 2.6 },
                borderRadius: 3.5,
                bgcolor: 'rgba(255, 145, 0, 0.12)',
                border: '1.5px solid rgba(255, 145, 0, 0.45)',
                color: '#FFE082',
                boxShadow: '0 12px 40px rgba(255, 145, 0, 0.15)',
                alignItems: 'center',
                '& .MuiAlert-icon': { alignItems: 'center' },
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: { xs: '1rem', sm: '1.14rem' }, lineHeight: 1.6 }}>
                حتى لو كان حسابك محمياً برمز تحقق (2FA)، فقد قمت بتسليم الرمز للمهاجم.
              </Typography>
              <Typography variant="body2" sx={{ color: 'rgba(255, 224, 130, 0.85)', mt: 0.6, fontSize: '0.86rem' }}>
                في هجمات الهندسة الاجتماعية المعاصرة، يقوم المهاجم بإنشاء صفحة اعتراض تطلب رمز التحقق فوراً وتستخدمه للدخول إلى حسابك قبل انتهاء صلاحيته.
              </Typography>
            </Alert>
          </motion.div>
        )}

        {/* --------------------- forensic evidence --------------------- */}
        <ImpactEvidenceCard trackingUuid={trackingUuid} />

        {/* --------------------- compromised assets --------------------- */}
        {compromisedAssets.length > 0 ? (
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.12 }}
          >
            <Box
              sx={{
                mb: { xs: 3, md: 4 },
                p: { xs: 2, sm: 2.6 },
                borderRadius: 4,
                border: '1px solid rgba(255,23,68,.28)',
                background:
                  'radial-gradient(circle at 100% 0%, rgba(255,23,68,.12), transparent 44%), linear-gradient(150deg, rgba(38,20,31,.9), rgba(12,15,26,.9))',
                boxShadow: '0 24px 70px rgba(0,0,0,.36)',
              }}
            >
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                justifyContent="space-between"
                alignItems={{ xs: 'flex-start', sm: 'center' }}
                spacing={1}
                sx={{ mb: 1.2 }}
              >
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box
                    sx={{
                      width: 38,
                      height: 38,
                      borderRadius: 2,
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: 'rgba(255,23,68,.1)',
                      border: '1px solid rgba(255,23,68,.25)',
                      color: '#FF6B81',
                    }}
                  >
                    <ShieldAlert size={20} />
                  </Box>
                  <Box>
                    <Typography sx={{ fontWeight: 900, fontSize: { xs: '1rem', sm: '1.12rem' } }}>
                      ما الذي حصل عليه المهاجم؟
                    </Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      هذه هي الأصول التي كانت بياناتك ستفتحها في هجوم حقيقي.
                    </Typography>
                  </Box>
                </Stack>
                <Chip
                  size="small"
                  label="محاكاة — لا ضرر فعلي"
                  color="error"
                  variant="outlined"
                  sx={{ fontWeight: 800 }}
                />
              </Stack>
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
                  gap: 1,
                  mt: 1.5,
                }}
              >
                {compromisedAssets.map((asset) => {
                  const AssetIcon = assetIcon(asset);
                  return (
                    <Stack
                      key={asset}
                      direction="row"
                      spacing={1.1}
                      alignItems="center"
                      sx={{
                        p: 1.25,
                        borderRadius: 2.5,
                        border: '1px solid rgba(255,255,255,.08)',
                        bgcolor: 'rgba(255,255,255,.025)',
                      }}
                    >
                      <Box
                        sx={{
                          width: 34,
                          height: 34,
                          borderRadius: 2,
                          display: 'grid',
                          placeItems: 'center',
                          color: '#FF8A9A',
                          bgcolor: 'rgba(255,23,68,.08)',
                          flex: '0 0 auto',
                        }}
                      >
                        <AssetIcon size={17} />
                      </Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontWeight: 800, fontSize: '0.84rem', lineHeight: 1.5 }}>
                          {asset}
                        </Typography>
                        {ASSET_ENGLISH[asset] ? (
                          <Typography
                            variant="caption"
                            sx={{ display: 'block', color: 'text.secondary', fontSize: '0.66rem' }}
                          >
                            {ASSET_ENGLISH[asset]}
                          </Typography>
                        ) : null}
                      </Box>
                    </Stack>
                  );
                })}
              </Box>
            </Box>
          </motion.div>
        ) : null}

        {/* ------------------- email teardown + countdown ------------------- */}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', lg: '1.35fr .85fr' },
            gap: 2.25,
            alignItems: 'start',
          }}
        >
          <motion.div
            initial={{ opacity: 0, x: 18 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.55, delay: 0.1 }}
          >
            <Box
              sx={{
                p: { xs: 1.25, sm: 1.75 },
                borderRadius: 4,
                border: '1px solid rgba(255,255,255,.10)',
                background: 'linear-gradient(150deg, rgba(25,36,59,.78), rgba(10,16,29,.82))',
                backdropFilter: 'blur(16px)',
                boxShadow: '0 30px 80px rgba(0,0,0,.42)',
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5, px: 0.5 }}>
                <Box>
                  <Typography sx={{ fontWeight: 800, fontSize: '0.95rem' }}>
                    {content.previewKind === 'email' ? 'الرسالة التي وصلتك' : content.label}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.7rem' }}>
                    اضغط على الدوائر الحمراء لكشف المؤشر
                  </Typography>
                </Box>
                <Chip
                  size="small"
                  icon={<AlertTriangle size={13} />}
                  label={`${discovered.length} / ${content.redFlags.length} مؤشرات`}
                  color={discovered.length === content.redFlags.length ? 'success' : 'error'}
                  variant="outlined"
                />
              </Stack>
              {content.previewKind === 'email' ? (
                <SimulatedEmail
                  context={context}
                  activeFlag={activeFlag}
                  onFlag={discover}
                  onCloseFlag={() => setActiveFlag(null)}
                />
              ) : (
                <SimulationPreview
                  context={context}
                  redFlags={content.redFlags}
                  activeFlag={activeFlag}
                  onFlag={discover}
                  onCloseFlag={() => setActiveFlag(null)}
                />
              )}
              <Box sx={{ mt: 1.5, px: 0.5 }}>
                <LinearProgress variant="determinate" value={progress} sx={{ height: 5, borderRadius: 99 }} />
              </Box>
            </Box>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: -18 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.55, delay: 0.18 }}
          >
            <Stack spacing={2}>
              <Box
                sx={{
                  p: 2.25,
                  borderRadius: 4,
                  border: '1px solid rgba(0,240,255,.16)',
                  background: 'linear-gradient(160deg, rgba(25,36,59,.82), rgba(10,16,29,.88))',
                  backdropFilter: 'blur(16px)',
                  boxShadow: '0 30px 80px rgba(0,0,0,.4)',
                }}
              >
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 1.4 }}>
                  <Timer size={17} color="#00F0FF" />
                  <Typography sx={{ fontWeight: 800, fontSize: '0.92rem' }}>وقت القراءة</Typography>
                </Stack>
                <CountdownRing remaining={remaining} />
                <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', color: 'text.secondary', mt: 1.2, lineHeight: 1.7 }}>
                  {ready ? 'انتهى العد. يمكنك الآن اختبار فهمك.' : 'خذ وقتك في قراءة المؤشرات. سيُفتح الاختبار بعد انتهاء العد.'}
                </Typography>
              </Box>

              <Box
                sx={{
                  p: 2.25,
                  borderRadius: 4,
                  border: '1px solid rgba(255,255,255,.10)',
                  background: 'linear-gradient(160deg, rgba(25,36,59,.78), rgba(10,16,29,.86))',
                  backdropFilter: 'blur(16px)',
                }}
              >
                <Typography sx={{ fontWeight: 800, fontSize: '0.92rem', mb: 1.2 }}>قائمة المؤشرات</Typography>
                <Stack spacing={1}>
                  {content.redFlags.map((flag) => {
                    const found = discovered.includes(flag.id);
                    const FlagIcon = flag.icon;
                    return (
                      <Box
                        key={flag.id}
                        component="button"
                        type="button"
                        onClick={() => discover(flag.id)}
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 1.1,
                          width: '100%',
                          textAlign: 'start',
                          border: `1px solid ${found ? alpha('#00E676', 0.25) : 'rgba(255,255,255,.08)'}`,
                          borderRadius: 2,
                          bgcolor: found ? 'rgba(0,230,118,.045)' : 'rgba(255,255,255,.02)',
                          color: 'text.primary',
                          p: 1,
                          cursor: 'pointer',
                          transition: 'all .2s ease',
                          '&:hover': { borderColor: 'rgba(255,23,68,.3)', bgcolor: 'rgba(255,23,68,.035)' },
                        }}
                      >
                        <Box
                          sx={{
                            width: 30,
                            height: 30,
                            borderRadius: 1.5,
                            display: 'grid',
                            placeItems: 'center',
                            color: found ? 'success.main' : '#FF6B81',
                            bgcolor: found ? 'rgba(0,230,118,.08)' : 'rgba(255,23,68,.08)',
                            flex: '0 0 auto',
                          }}
                        >
                          {found ? <CheckCircle2 size={15} /> : <FlagIcon size={15} />}
                        </Box>
                        <Box sx={{ minWidth: 0, flex: 1 }}>
                          <Typography sx={{ fontSize: '0.75rem', fontWeight: 700, lineHeight: 1.5 }}>{flag.title}</Typography>
                          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.64rem' }}>
                            {found ? 'تم الكشف — اضغط للمراجعة' : 'اضغط للكشف'}
                          </Typography>
                        </Box>
                      </Box>
                    );
                  })}
                </Stack>
              </Box>

              {content.previewKind === 'email' ? (
                <Box
                  sx={{
                    p: 1.5,
                    borderRadius: 3,
                    border: reported ? '1px solid rgba(0,230,118,.3)' : '1px solid rgba(255,255,255,.09)',
                    bgcolor: reported ? 'rgba(0,230,118,.05)' : 'rgba(255,255,255,.02)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.2,
                  }}
                >
                  <Box sx={{ width: 32, height: 32, borderRadius: 1.5, display: 'grid', placeItems: 'center', bgcolor: reported ? 'rgba(0,230,118,.1)' : 'rgba(255,23,68,.08)', color: reported ? 'success.main' : '#FF6B81' }}>
                    {reported ? <BadgeCheck size={16} /> : <Flag size={16} />}
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <Typography sx={{ fontSize: '0.74rem', fontWeight: 700 }}>
                      {reported ? 'تم تسجيل البلاغ — أحسنت' : 'هل أدركت أنها محاولة تصيّد؟'}
                    </Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.63rem' }}>
                      {reported ? 'أبلغت عن الرسالة كتصيّد.' : 'أبلغ عنها الآن لتعزيز مناعتك.'}
                    </Typography>
                  </Box>
                  {!reported ? (
                    <Button size="small" variant="outlined" color="error" disabled={reportBusy} onClick={() => void reportPhishing()}>
                      {reportBusy ? '...' : 'أبلغ'}
                    </Button>
                  ) : null}
                </Box>
              ) : null}
            </Stack>
          </motion.div>
        </Box>

        {/* ------------------------------ quiz ------------------------------ */}
        <Box
          sx={{
            mt: 3,
            p: { xs: 2, sm: 3 },
            borderRadius: 4,
            border: '1px solid rgba(0,240,255,.16)',
            background: 'linear-gradient(150deg, rgba(25,36,59,.84), rgba(10,16,29,.9))',
            boxShadow: '0 30px 80px rgba(0,0,0,.4)',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <Box className="mc-scan" sx={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.5 }} />
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={1.5} sx={{ mb: 2, position: 'relative', zIndex: 1 }}>
            <Box>
              <Typography variant="overline" sx={{ color: 'primary.main', fontSize: '0.62rem', letterSpacing: '.14em' }}>
                KNOWLEDGE CHECK · 5 QUESTIONS
              </Typography>
              <Typography sx={{ fontSize: { xs: '1.1rem', md: '1.3rem' }, fontWeight: 800, lineHeight: 1.5 }}>
                اختبر ما تعلمته من تفكيك المحتوى
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
                لكل إجابة صحيحة +1، ولكل إجابة خاطئة -1. لا يمكن تغيير الإجابة بعد اختيارها.
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} alignItems="center">
              <Chip
                icon={ready ? <Sparkles size={13} /> : <Clock3 size={13} />}
                label={ready ? `${answeredCount} / ${content.quiz.length} answered` : `يفتح بعد ${remaining} ثانية`}
                color={ready ? 'success' : 'default'}
                variant="outlined"
              />
              <Chip
                label={`${quizScore} / ${content.quiz.length}`}
                color={quizScore === content.quiz.length ? 'success' : 'primary'}
                variant="filled"
              />
            </Stack>
          </Stack>

          {!ready ? (
            <Box sx={{ py: 3, textAlign: 'center', position: 'relative', zIndex: 1 }}>
              <LockKeyhole size={26} color="#8B9BB4" />
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                اقرأ المؤشرات أولاً. ستُفتح الأسئلة الخمسة تلقائياً بعد انتهاء العد.
              </Typography>
            </Box>
          ) : (
            <Box sx={{ position: 'relative', zIndex: 1 }}>
              <Stack spacing={1.5}>
                {content.quiz.map((question, questionIndex) => {
                  const selected = answers[question.id];
                  const answered = Boolean(selected);
                  const isCorrect = selected === question.correct;
                  const correctOption = question.options.find((option) => option.id === question.correct);
                  return (
                    <Box
                      key={question.id}
                      sx={{
                        p: { xs: 1.5, sm: 2 },
                        borderRadius: 3,
                        border: answered
                          ? isCorrect
                            ? '1px solid rgba(0,230,118,.35)'
                            : '1px solid rgba(255,23,68,.35)'
                          : '1px solid rgba(255,255,255,.08)',
                        bgcolor: answered
                          ? isCorrect
                            ? 'rgba(0,230,118,.035)'
                            : 'rgba(255,23,68,.035)'
                          : 'rgba(255,255,255,.015)',
                      }}
                    >
                      <Stack direction="row" spacing={1.2} alignItems="flex-start" sx={{ mb: 1.2 }}>
                        <Chip size="small" label={`سؤال ${questionIndex + 1}`} color="primary" variant="outlined" />
                        <Typography sx={{ fontSize: '0.88rem', fontWeight: 700, lineHeight: 1.65 }}>
                          {question.prompt}
                        </Typography>
                      </Stack>
                      <Stack spacing={0.9}>
                        {question.options.map((option, optionIndex) => {
                          const optionSelected = selected === option.id;
                          const revealedCorrect = answered && option.id === question.correct;
                          const revealedWrong = answered && optionSelected && option.id !== question.correct;
                          return (
                            <motion.div key={option.id} whileHover={answered ? undefined : { x: -3 }} whileTap={answered ? undefined : { scale: 0.995 }}>
                              <Box
                                component="button"
                                type="button"
                                onClick={() => selectAnswer(question.id, option.id)}
                                disabled={answered}
                                sx={{
                                  width: '100%',
                                  textAlign: 'start',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 1.2,
                                  p: 1.2,
                                  borderRadius: 2,
                                  border: revealedCorrect
                                    ? '1px solid rgba(0,230,118,.5)'
                                    : revealedWrong
                                      ? '1px solid rgba(255,23,68,.5)'
                                      : optionSelected
                                        ? '1px solid rgba(0,240,255,.45)'
                                        : '1px solid rgba(255,255,255,.08)',
                                  bgcolor: revealedCorrect
                                    ? 'rgba(0,230,118,.06)'
                                    : revealedWrong
                                      ? 'rgba(255,23,68,.06)'
                                      : optionSelected
                                        ? 'rgba(0,240,255,.05)'
                                        : 'rgba(255,255,255,.018)',
                                  color: 'text.primary',
                                  cursor: answered ? 'default' : 'pointer',
                                  transition: 'all .2s ease',
                                  '&:hover': answered ? {} : { borderColor: 'rgba(0,240,255,.35)', bgcolor: 'rgba(0,240,255,.04)' },
                                }}
                              >
                                <Box
                                  sx={{
                                    width: 32,
                                    height: 32,
                                    borderRadius: 1.5,
                                    display: 'grid',
                                    placeItems: 'center',
                                    fontWeight: 800,
                                    fontSize: '0.76rem',
                                    color: revealedCorrect ? 'success.main' : revealedWrong ? '#FF6B81' : 'primary.main',
                                    bgcolor: revealedCorrect ? 'rgba(0,230,118,.1)' : revealedWrong ? 'rgba(255,23,68,.1)' : 'rgba(0,240,255,.07)',
                                    border: '1px solid rgba(255,255,255,.08)',
                                    flex: '0 0 auto',
                                  }}
                                >
                                  {revealedCorrect ? <CheckCircle2 size={16} /> : revealedWrong ? <XCircle size={16} /> : String.fromCharCode(65 + optionIndex)}
                                </Box>
                                <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, lineHeight: 1.55, flex: 1 }}>
                                  {option.text}
                                </Typography>
                                {optionSelected ? (
                                  <Chip
                                    size="small"
                                    label={isCorrect ? '+1' : '-1'}
                                    color={isCorrect ? 'success' : 'error'}
                                    sx={{ fontWeight: 900, minWidth: 44 }}
                                  />
                                ) : null}
                              </Box>
                            </motion.div>
                          );
                        })}
                      </Stack>
                      {answered ? (
                        <Alert
                          severity={isCorrect ? 'success' : 'error'}
                          sx={{ mt: 1.2, py: 0.35 }}
                          icon={isCorrect ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
                        >
                          <Typography sx={{ fontSize: '0.76rem', fontWeight: 700, lineHeight: 1.7 }}>
                            {isCorrect
                              ? `+1 — ${question.explanation}`
                              : `-1 — ${question.wrongHint} الإجابة الصحيحة: ${correctOption?.text ?? ''}`}
                          </Typography>
                        </Alert>
                      ) : null}
                    </Box>
                  );
                })}
              </Stack>

              <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} spacing={1.25} sx={{ mt: 2 }}>
                <Box>
                  <Typography sx={{ fontWeight: 800, fontSize: '0.82rem' }}>
                    النتيجة الحالية: {quizScore} من {content.quiz.length}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {quizComplete
                      ? 'أجبت على جميع الأسئلة. أرسل النتيجة لإكمال التدريب.'
                      : `أكمل ${content.quiz.length - answeredCount} سؤالاً متبقياً.`}
                  </Typography>
                </Box>
                <Button
                  variant="contained"
                  size="large"
                  disabled={!ready || !quizComplete || completing || completed}
                  onClick={() => void completeTraining()}
                  startIcon={completing ? undefined : <ShieldCheck size={18} />}
                  sx={{ minWidth: 250 }}
                >
                  {completing ? 'جارٍ تسجيل الإكمال…' : completed ? 'تم إكمال التدريب' : 'أرسل النتيجة وأكمل التدريب'}
                </Button>
              </Stack>

              {completeError ? (
                <Alert severity="error" sx={{ mt: 1.5 }}>
                  {completeError}
                </Alert>
              ) : null}
            </Box>
          )}
        </Box>

        {/* --------------------------- certificate --------------------------- */}
        <AnimatePresence>
          {completed ? (
            <motion.div
              key="certificate"
              initial={{ opacity: 0, y: 28, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
              style={{ marginTop: 28 }}
            >
              <Box ref={certificateRef} className="mc-certificate" sx={{ position: 'relative', borderRadius: 5, p: { xs: 2.5, sm: 4.5 }, overflow: 'hidden' }}>
                <Box sx={{ position: 'absolute', inset: 10, border: '1px solid rgba(0,240,255,.12)', borderRadius: 4, pointerEvents: 'none' }} />
                <Stack alignItems="center" textAlign="center" spacing={1.4} sx={{ position: 'relative', zIndex: 1 }}>
                  <Box
                    sx={{
                      width: 72,
                      height: 72,
                      borderRadius: '50%',
                      display: 'grid',
                      placeItems: 'center',
                      color: '#031018',
                      background: 'linear-gradient(135deg, #00F0FF, #7CFFB2)',
                      boxShadow: '0 0 44px rgba(0,240,255,.35)',
                      mb: 0.5,
                    }}
                  >
                    <Award size={36} />
                  </Box>
                  <Typography variant="overline" sx={{ color: 'primary.main', letterSpacing: '.2em' }}>
                    CERTIFICATE OF SECURITY IMMUNITY
                  </Typography>
                  <Typography sx={{ fontSize: { xs: '1.5rem', sm: '2rem' }, fontWeight: 800, lineHeight: 1.4 }}>
                    شهادة إتمام التوعية الأمنية
                  </Typography>
                  <Typography sx={{ color: 'text.secondary', maxWidth: 620, lineHeight: 1.9 }}>
                    تُمنح هذه الشهادة إلى{' '}
                    <Box component="span" sx={{ color: 'text.primary', fontWeight: 800 }}>
                      {displayName}
                    </Box>{' '}
                    تقديراً لإكماله {content.label} بنجاح.
                  </Typography>
                  <Typography
                    sx={{
                      fontSize: { xs: '1rem', sm: '1.2rem' },
                      fontWeight: 800,
                      color: 'success.main',
                      textShadow: '0 0 26px rgba(0,230,118,.32)',
                    }}
                  >
                    {finalScore !== null
                      ? `تهانينا! نتيجتك في الاختبار: ${finalScore} من ${finalTotal}.`
                      : 'تهانينا! تم تسجيل إكمالك للتدريب بنجاح.'}
                  </Typography>
                  <Chip
                    icon={<Award size={14} />}
                    label="شكراً لك — انتهت الجلسة التدريبية"
                    color="success"
                    variant="outlined"
                    sx={{ fontWeight: 800 }}
                  />

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.5, sm: 3 }} sx={{ pt: 2, color: 'text.secondary' }}>
                    <Typography variant="caption">المؤسسة: {context.company_name ?? '—'}</Typography>
                    <Typography variant="caption">
                      التاريخ: {new Date().toLocaleDateString('ar-JO', { year: 'numeric', month: 'long', day: 'numeric' })}
                    </Typography>
                    <Typography variant="caption" className="mc-mono" sx={{ direction: 'ltr' }}>
                      ID: {trackingUuid.slice(0, 8).toUpperCase()}
                    </Typography>
                  </Stack>

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.2} sx={{ pt: 1.5 }}>
                    <Button
                      variant="contained"
                      startIcon={<ShieldCheck size={17} />}
                      onClick={() => setSessionEnded(true)}
                    >
                      إنهاء الجلسة
                    </Button>
                    <Button
                      variant="outlined"
                      startIcon={<ExternalLink size={16} />}
                      onClick={() => {
                        setSessionEnded(true);
                        window.close();
                      }}
                    >
                      إغلاق النافذة
                    </Button>
                  </Stack>
                  <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.62rem', pt: 1 }}>
                    شكراً لمشاركتك. لا تحتوي هذه الصفحة على أي رابط إلى لوحة الإدارة.
                  </Typography>
                </Stack>
              </Box>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <Stack direction="row" spacing={1} alignItems="center" justifyContent="center" sx={{ mt: 4, color: 'text.disabled' }}>
          <ArrowLeft size={13} />
          <Typography variant="caption" sx={{ fontSize: '0.66rem' }}>
            HUMINT Shield · تدريب توعية أمنية مصرّح به
          </Typography>
        </Stack>
      </Container>
    </Box>
  );
}


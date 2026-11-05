import { useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Chip from '@mui/material/Chip';
import Alert from '@mui/material/Alert';
import TextField from '@mui/material/TextField';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import FormControlLabel from '@mui/material/FormControlLabel';
import Switch from '@mui/material/Switch';
import Checkbox from '@mui/material/Checkbox';
import Slider from '@mui/material/Slider';
import Divider from '@mui/material/Divider';
import Paper from '@mui/material/Paper';
import SecurityIcon from '@mui/icons-material/Security';
import LockResetIcon from '@mui/icons-material/LockReset';
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import HubIcon from '@mui/icons-material/Hub';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import TuneIcon from '@mui/icons-material/Tune';
import SaveIcon from '@mui/icons-material/Save';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import toast from 'react-hot-toast';

import { containmentApi } from '@/api/endpoints';

interface EnterpriseContainmentStationProps {
  campaignId: string;
}

export function EnterpriseContainmentStation({ campaignId }: EnterpriseContainmentStationProps) {
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [status, setStatus] = useState<any>(null);

  // Admin Policy State
  const [forcePasswordReset, setForcePasswordReset] = useState(true);
  const [revokeSessions, setRevokeSessions] = useState(true);
  const [quarantineAccount, setQuarantineAccount] = useState(false);
  const [enforceStrictPassword, setEnforceStrictPassword] = useState(true);
  const [enforceMfa, setEnforceMfa] = useState(true);
  const [notifySoar, setNotifySoar] = useState(true);

  // Password Complexity Rules
  const [minLength, setMinLength] = useState<number>(16);
  const [requireSymbols, setRequireSymbols] = useState(true);
  const [requireNumbers, setRequireNumbers] = useState(true);
  const [requireUppercase, setRequireUppercase] = useState(true);
  const [historyCount, setHistoryCount] = useState<number>(10);
  const [lockoutThreshold, setLockoutThreshold] = useState<number>(5);

  // Interactive Test State
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [targetIdentity, setTargetIdentity] = useState('khalid.salem@company.local');
  const [breachType, setBreachType] = useState('badusb_hid');
  const [triggering, setTriggering] = useState(false);
  const [lastReport, setLastReport] = useState<any>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [stat, pol] = await Promise.all([
          containmentApi.getStatus(),
          containmentApi.getPolicy(),
        ]);
        setStatus(stat);
        if (pol) {
          setForcePasswordReset(pol.force_password_reset ?? true);
          setRevokeSessions(pol.revoke_sessions ?? true);
          setQuarantineAccount(pol.quarantine_account ?? false);
          setEnforceStrictPassword(pol.enforce_strict_password ?? true);
          setEnforceMfa(pol.enforce_mfa ?? true);
          setNotifySoar(pol.notify_soar ?? true);

          if (pol.password_policy) {
            setMinLength(pol.password_policy.min_length ?? 16);
            setRequireSymbols(pol.password_policy.require_symbols ?? true);
            setRequireNumbers(pol.password_policy.require_numbers ?? true);
            setRequireUppercase(pol.password_policy.require_uppercase ?? true);
            setHistoryCount(pol.password_policy.history_count ?? 10);
            setLockoutThreshold(pol.password_policy.lockout_threshold ?? 5);
          }
        }
      } catch (err) {
        console.error('Failed to load containment settings', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  async function handleSavePolicy() {
    setSavingPolicy(true);
    try {
      const payload = {
        auto_containment_enabled: true,
        force_password_reset: forcePasswordReset,
        revoke_sessions: revokeSessions,
        quarantine_account: quarantineAccount,
        enforce_strict_password: enforceStrictPassword,
        enforce_mfa: enforceMfa,
        notify_soar: notifySoar,
        password_policy: {
          min_length: minLength,
          require_symbols: requireSymbols,
          require_numbers: requireNumbers,
          require_uppercase: requireUppercase,
          require_lowercase: true,
          history_count: historyCount,
          max_age_days: 30,
          lockout_threshold: lockoutThreshold,
        },
      };
      await containmentApi.updatePolicy(payload);
      toast.success('تم حفظ سياسة الأدمن وتحديث قواعد البنية التحتية بنجاح 🛡️');
    } catch (err: any) {
      toast.error(err?.message || 'فشل حفظ سياسة الاستجابة');
    } finally {
      setSavingPolicy(false);
    }
  }

  async function handleTriggerTest() {
    if (!targetIdentity.trim()) {
      toast.error('يرجى إدخال اسم المستخدم أو البريد الإلكتروني للموظف');
      return;
    }
    setTriggering(true);
    setLastReport(null);
    try {
      const rep = await containmentApi.triggerContainment({
        target_identity: targetIdentity.trim(),
        breach_type: breachType,
        campaign_id: campaignId,
        policy_override: {
          auto_containment_enabled: true,
          force_password_reset: forcePasswordReset,
          revoke_sessions: revokeSessions,
          quarantine_account: quarantineAccount,
          enforce_strict_password: enforceStrictPassword,
          enforce_mfa: enforceMfa,
          notify_soar: notifySoar,
          password_policy: {
            min_length: minLength,
            require_symbols: requireSymbols,
            require_numbers: requireNumbers,
            require_uppercase: requireUppercase,
            require_lowercase: true,
            history_count: historyCount,
            max_age_days: 30,
            lockout_threshold: lockoutThreshold,
          },
        },
      });
      setLastReport(rep);
      toast.success('تم تطبيق سياسة الأدمن المخصصة على الموظف بنجاح');
    } catch (err: any) {
      toast.error(err?.message || 'فشل تنفيذ استجابة الدليل النشط');
    } finally {
      setTriggering(false);
    }
  }

  // Live generated PowerShell Fine-Grained Password Policy Cmdlet
  const generatedPsCmd = `New-ADFineGrainedPasswordPolicy -Name 'HUMINT_Strict_Enforcement' -Precedence 1 -ComplexityEnabled $true -MinPasswordLength ${minLength} -PasswordHistoryCount ${historyCount} -LockoutThreshold ${lockoutThreshold} -AppliesTo 'Enforced_Strict_Password_Group'`;

  const getStrengthBadge = (len: number) => {
    if (len >= 16) return { label: 'حصين جداً (NSA / NIST 800-63B)', color: 'success' as const };
    if (len >= 12) return { label: 'قوي (Enterprise Standard)', color: 'primary' as const };
    return { label: 'متوسط (Basic Complexity)', color: 'warning' as const };
  };

  const strength = getStrengthBadge(minLength);

  if (loading) {
    return (
      <Card sx={{ mb: 3, p: 3, textAlign: 'center' }}>
        <CircularProgress size={24} sx={{ mr: 1 }} />
        <Typography variant="body2" sx={{ display: 'inline' }}>
          جاري تحميل منظومة وسياسات الربط مع البنية التحتية...
        </Typography>
      </Card>
    );
  }

  return (
    <Card
      sx={{
        mb: 3,
        border: '1px solid',
        borderColor: 'primary.dark',
        bgcolor: 'background.paper',
        boxShadow: (t) => `0 4px 20px ${t.palette.mode === 'dark' ? 'rgba(0,0,0,0.5)' : 'rgba(15,108,189,0.08)'}`,
      }}
    >
      <CardContent sx={{ p: 3 }}>
        {/* Header */}
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          alignItems={{ xs: 'flex-start', md: 'center' }}
          justifyContent="space-between"
          spacing={2}
          sx={{ mb: 2.5 }}
        >
          <Box>
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 0.5 }}>
              <AdminPanelSettingsIcon color="primary" sx={{ fontSize: 30 }} />
              <Typography variant="h6" fontWeight={800}>
                لوحة تحكم الأدمن في استجابة البنية التحتية (Infrastructure Remediation & Password Policy)
              </Typography>
              <Chip
                label={status?.containment_enabled ? 'متصل ومفعّل' : 'وضع المحاكاة الآمن'}
                size="small"
                color="success"
                icon={<CheckCircleIcon sx={{ fontSize: '16px !important' }} />}
                sx={{ fontWeight: 700 }}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              أنت كمدير للنظام تحدد الإجراءات الصارمة التي تُنفذ فوراً على حساب الموظف المخترق في Active Directory / Entra ID، وتحدد بدقة متناهية شروط قوة كلمة المرور الجديدة.
            </Typography>
          </Box>

          <Stack direction="row" spacing={1.5}>
            <Button
              variant="outlined"
              color="primary"
              startIcon={<PlayArrowIcon />}
              onClick={() => setTestModalOpen(true)}
              sx={{ fontWeight: 700 }}
            >
              تجربة الاحتواء على حساب
            </Button>
            <Button
              variant="contained"
              color="primary"
              startIcon={savingPolicy ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
              onClick={handleSavePolicy}
              disabled={savingPolicy}
              sx={{ fontWeight: 700, px: 2.5 }}
            >
              حفظ السياسة واعتمادها
            </Button>
          </Stack>
        </Stack>

        {/* Integration Status Badges */}
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 3 }}>
          <Box
            sx={{
              flex: 1,
              p: 1.5,
              borderRadius: 1.5,
              border: '1px solid',
              borderColor: 'divider',
              bgcolor: 'action.hover',
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
              <HubIcon fontSize="small" color="primary" />
              <Typography variant="caption" fontWeight={700}>
                Active Directory (On-Premises AD DS)
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block">
              تطبيق Fine-Grained Password Policy (FGPP) وتصفير pwdLastSet = 0 عبر PowerShell
            </Typography>
          </Box>

          <Box
            sx={{
              flex: 1,
              p: 1.5,
              borderRadius: 1.5,
              border: '1px solid',
              borderColor: 'divider',
              bgcolor: 'action.hover',
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
              <SecurityIcon fontSize="small" color="secondary" />
              <Typography variant="caption" fontWeight={700}>
                Microsoft Entra ID (M365 / Azure AD)
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block">
              إلغاء وتدمير الـ Refresh Tokens وجلسات الدخول وإجبار التغيير عبر Microsoft Graph API
            </Typography>
          </Box>

          <Box
            sx={{
              flex: 1,
              p: 1.5,
              borderRadius: 1.5,
              border: '1px solid',
              borderColor: 'divider',
              bgcolor: 'action.hover',
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
              <PowerSettingsNewIcon fontSize="small" color="warning" />
              <Typography variant="caption" fontWeight={700}>
                SOAR / SOC Webhooks
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block">
              بث إشارة التهديد الآلية مع تصنيف MITRE T1091/T1566 لمنصات التحليل الأمني
            </Typography>
          </Box>
        </Stack>

        <Divider sx={{ mb: 3 }} />

        {/* SECTION 1: Remediations Selection */}
        <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
          <TuneIcon color="primary" fontSize="small" />
          1. تحديد الإجراءات التنفيذية التي تُتخذ ضد الموظف المخترق (Remediation Actions)
        </Typography>

        <Paper variant="outlined" sx={{ p: 2, mb: 3, bgcolor: 'background.default' }}>
          <Stack spacing={1.5}>
            <FormControlLabel
              control={
                <Switch
                  checked={forcePasswordReset}
                  onChange={(e) => setForcePasswordReset(e.target.checked)}
                  color="primary"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" fontWeight={700}>
                    إجبار الموظف على تغيير كلمة المرور فور تسجيل الدخول القادم (Force Password Reset)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    يتم تصفير خاصية (pwdLastSet = 0) في Active Directory، و (forceChangePasswordNextSignIn: true) في Entra ID
                  </Typography>
                </Box>
              }
            />

            <FormControlLabel
              control={
                <Switch
                  checked={revokeSessions}
                  onChange={(e) => setRevokeSessions(e.target.checked)}
                  color="primary"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" fontWeight={700}>
                    إبطال وطرد كافة جلسات تسجيل الدخول والرموز المميزة فوراً (Revoke Active Sessions)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    يطرد الموظف فوراً من كافة الأجهزة والمتصفحات، ويُبطل Refresh Tokens في Outlook و Teams لمنع سرقة الجلسة
                  </Typography>
                </Box>
              }
            />

            <FormControlLabel
              control={
                <Switch
                  checked={quarantineAccount}
                  onChange={(e) => setQuarantineAccount(e.target.checked)}
                  color="error"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" fontWeight={700} color={quarantineAccount ? 'error.main' : 'text.primary'}>
                    إيقاف وتجميد الحساب كلياً كإجراء عزل مؤقت (Quarantine / Suspend Account)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    يتم تعطيل الحساب (Disable-ADAccount) لمنع وصول الموظف للشبكة حتى إشعار آخر من فريق الأمن
                  </Typography>
                </Box>
              }
            />

            <FormControlLabel
              control={
                <Switch
                  checked={enforceStrictPassword}
                  onChange={(e) => setEnforceStrictPassword(e.target.checked)}
                  color="primary"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" fontWeight={700}>
                    فرض سياسة كلمات مرور صارمة ومخصصة (Enforce Fine-Grained Strict Password Policy)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    يمنع الموظف من تعيين كلمة مرور سهلة، ويُلزمه بالقواعد المحددة في القسم أدناه
                  </Typography>
                </Box>
              }
            />

            <FormControlLabel
              control={
                <Switch
                  checked={notifySoar}
                  onChange={(e) => setNotifySoar(e.target.checked)}
                  color="primary"
                />
              }
              label={
                <Box>
                  <Typography variant="body2" fontWeight={700}>
                    إرسال بلاغ فوري لغرفة العمليات الأمنية (SOC / SIEM Webhook Dispatch)
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    إرسال تذكرة أمنية فورية إلى Microsoft Sentinel أو Splunk أو Wazuh
                  </Typography>
                </Box>
              }
            />
          </Stack>
        </Paper>

        {/* SECTION 2: Custom Password Complexity Control */}
        <Typography variant="subtitle1" fontWeight={800} sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
          <VpnKeyIcon color="primary" fontSize="small" />
          2. التحكم في قوة وتعقيد كلمة المرور الجديدة (Custom Password Complexity Builder)
        </Typography>

        <Paper variant="outlined" sx={{ p: 2.5, mb: 3, bgcolor: 'background.default' }}>
          {/* Slider for Min Length */}
          <Box sx={{ mb: 3 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="body2" fontWeight={700}>
                الحد الأدنى لعدد أحرف كلمة المرور (Minimum Password Length):
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <Chip label={`${minLength} خانة`} color={strength.color} sx={{ fontWeight: 800, fontSize: '0.85rem' }} />
                <Chip label={strength.label} variant="outlined" size="small" color={strength.color} />
              </Stack>
            </Stack>
            <Slider
              value={minLength}
              min={8}
              max={32}
              step={1}
              marks={[
                { value: 8, label: '8' },
                { value: 12, label: '12 (معيار قياسي)' },
                { value: 16, label: '16 (موصى به)' },
                { value: 20, label: '20 (حساس جداً)' },
                { value: 32, label: '32' },
              ]}
              onChange={(_, val) => setMinLength(val as number)}
              sx={{ color: strength.color === 'success' ? '#2e7d32' : undefined }}
            />
          </Box>

          {/* Complexity Checkboxes */}
          <Typography variant="caption" fontWeight={700} color="text.secondary" display="block" sx={{ mb: 1 }}>
            اشتراطات الرموز والتعقيد (Complexity Requirements):
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2.5 }}>
            <FormControlLabel
              control={<Checkbox checked={requireSymbols} onChange={(e) => setRequireSymbols(e.target.checked)} />}
              label={<Typography variant="body2" fontWeight={600}>اشتراط رموز خاصة (!@#$%^&*...)</Typography>}
            />
            <FormControlLabel
              control={<Checkbox checked={requireNumbers} onChange={(e) => setRequireNumbers(e.target.checked)} />}
              label={<Typography variant="body2" fontWeight={600}>اشتراط أرقام (0-9)</Typography>}
            />
            <FormControlLabel
              control={<Checkbox checked={requireUppercase} onChange={(e) => setRequireUppercase(e.target.checked)} />}
              label={<Typography variant="body2" fontWeight={600}>اشتراط أحرف كبيرة وصغيرة (A-Z, a-z)</Typography>}
            />
          </Stack>

          {/* Advanced Rules */}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              label="منع تكرار آخر كلمات مرور (Password History)"
              size="small"
              type="number"
              value={historyCount}
              onChange={(e) => setHistoryCount(Math.max(0, parseInt(e.target.value) || 0))}
              helperText="يمنع الموظف من إعادة استخدام آخر 10 كلمات مثلاً"
              sx={{ flex: 1 }}
            />
            <TextField
              label="عدد المحاولات الخاطئة قبل القفل (Lockout Threshold)"
              size="small"
              type="number"
              value={lockoutThreshold}
              onChange={(e) => setLockoutThreshold(Math.max(1, parseInt(e.target.value) || 1))}
              helperText="يقفل الحساب بعد 5 محاولات فاشلة للحماية من هجمات التخمين"
              sx={{ flex: 1 }}
            />
          </Stack>

          {/* Live PowerShell AD Cmdlet Preview */}
          <Box sx={{ mt: 2.5, p: 1.5, borderRadius: 1.5, bgcolor: '#0f172a', border: '1px solid #1e293b' }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
              <Typography variant="caption" sx={{ color: '#38bdf8', fontWeight: 800 }}>
                ⚡ أمر الـ Active Directory المولد تلقائياً للبنية التحتية (FGPP Cmdlet):
              </Typography>
              <Chip label="PowerShell Live" size="small" sx={{ height: 18, fontSize: 10, bgcolor: '#1e293b', color: '#94a3b8' }} />
            </Stack>
            <Typography
              variant="caption"
              sx={{
                fontFamily: 'Consolas, monospace',
                color: '#f8fafc',
                display: 'block',
                wordBreak: 'break-all',
                direction: 'ltr',
                textAlign: 'left',
              }}
            >
              {generatedPsCmd}
            </Typography>
          </Box>
        </Paper>

        <Alert severity="success" variant="outlined" sx={{ py: 0.75, fontSize: 13 }}>
          <strong>مرونة كاملة للأدمن:</strong> بمجرد حفظ السياسة أعلاه، فإن أي موظف يقع في فخ التوعية (USB أو Phishing) ستُطبق عليه فوراً هذه القرارات بدقة متناهية ودون تدخل يدوي إضافي.
        </Alert>
      </CardContent>

      {/* Interactive Simulation Modal */}
      <Dialog open={testModalOpen} onClose={() => setTestModalOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <LockResetIcon color="primary" />
            <Typography variant="h6" fontWeight={800}>
              محاكاة تطبيق قرارات الأدمن على حساب موظف
            </Typography>
          </Stack>
          <Chip label="Admin Policy Execution" size="small" color="primary" />
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            حدد معرّف الموظف لاختبار تنفيذ حزمة الإجراءات التي قمت بضبطها في لوحة التحكم أعلاه:
          </Typography>

          <Stack spacing={2} sx={{ mb: 3 }}>
            <TextField
              label="معرّف الموظف (البريد المؤسسي أو اسم حساب الويندوز)"
              fullWidth
              size="small"
              value={targetIdentity}
              onChange={(e) => setTargetIdentity(e.target.value)}
              placeholder="e.g. khalid.salem@company.local أو akhalid"
            />

            <Stack direction="row" spacing={1}>
              <Chip
                label="BadUSB HID Injection"
                color={breachType === 'badusb_hid' ? 'primary' : 'default'}
                onClick={() => setBreachType('badusb_hid')}
                clickable
              />
              <Chip
                label="USB Baiting Drop"
                color={breachType === 'usb_baiting' ? 'primary' : 'default'}
                onClick={() => setBreachType('usb_baiting')}
                clickable
              />
              <Chip
                label="Credential Phishing Submission"
                color={breachType === 'credential_phish' ? 'primary' : 'default'}
                onClick={() => setBreachType('credential_phish')}
                clickable
              />
            </Stack>
          </Stack>

          <Button
            variant="contained"
            color="primary"
            fullWidth
            size="large"
            onClick={handleTriggerTest}
            disabled={triggering}
            startIcon={triggering ? <CircularProgress size={20} color="inherit" /> : <PlayArrowIcon />}
            sx={{ py: 1.2, fontWeight: 700 }}
          >
            {triggering ? 'جاري تنفيذ سياسة الأدمن في الدليل النشط...' : 'تنفيذ قرارات الأدمن على الحساب الآن'}
          </Button>

          {lastReport && (
            <Box
              sx={{
                mt: 3,
                p: 2,
                borderRadius: 2,
                bgcolor: (t) => (t.palette.mode === 'dark' ? '#0a101d' : '#f0f7ff'),
                border: '1px solid',
                borderColor: 'primary.light',
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                <Typography variant="subtitle2" fontWeight={800} color="primary">
                  إيصال تنفيذ السياسة (Policy Enforcement Receipt):
                </Typography>
                <Chip label={lastReport.overall_status.toUpperCase()} color="success" size="small" />
              </Stack>

              <Typography variant="body2" sx={{ mb: 2, fontWeight: 700 }}>
                {lastReport.summary_ar}
              </Typography>

              <Stack spacing={1}>
                {lastReport.results?.map((res: any, idx: number) => (
                  <Box
                    key={idx}
                    sx={{
                      p: 1.25,
                      borderRadius: 1,
                      bgcolor: 'background.paper',
                      border: '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <CheckCircleIcon color="success" sx={{ fontSize: 18 }} />
                        <Typography variant="body2" fontWeight={700}>
                          {res.action}
                        </Typography>
                      </Stack>
                      <Chip label={res.provider} size="small" variant="outlined" sx={{ fontSize: 11 }} />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      {res.message_ar}
                    </Typography>
                    {res.details && (
                      <Box
                        sx={{
                          mt: 0.5,
                          p: 0.75,
                          bgcolor: 'action.hover',
                          borderRadius: 0.5,
                          fontFamily: 'monospace',
                          fontSize: 11,
                          direction: 'ltr',
                          textAlign: 'left',
                        }}
                      >
                        {JSON.stringify(res.details)}
                      </Box>
                    )}
                  </Box>
                ))}
              </Stack>
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setTestModalOpen(false)}>إغلاق</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

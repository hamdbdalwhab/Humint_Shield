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
import SecurityIcon from '@mui/icons-material/Security';
import LockResetIcon from '@mui/icons-material/LockReset';
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import HubIcon from '@mui/icons-material/Hub';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import toast from 'react-hot-toast';

import { containmentApi } from '@/api/endpoints';

interface EnterpriseContainmentStationProps {
  campaignId: string;
}

export function EnterpriseContainmentStation({ campaignId }: EnterpriseContainmentStationProps) {
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [status, setStatus] = useState<any>(null);
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [targetIdentity, setTargetIdentity] = useState('khalid.salem@company.local');
  const [breachType, setBreachType] = useState('badusb_hid');
  const [triggering, setTriggering] = useState(false);
  const [lastReport, setLastReport] = useState<any>(null);

  useEffect(() => {
    containmentApi
      .getStatus()
      .then((data) => {
        setStatus(data);
      })
      .catch((err) => {
        console.error('Failed to fetch containment status', err);
      })
      .finally(() => {
        setLoadingStatus(false);
      });
  }, []);

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
      });
      setLastReport(rep);
      toast.success('تم تنفيذ إجراءات الاستجابة والاحتواء بنجاح في الدليل النشط');
    } catch (err: any) {
      toast.error(err?.message || 'فشل تنفيذ استجابة الدليل النشط');
    } finally {
      setTriggering(false);
    }
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
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          alignItems={{ xs: 'flex-start', md: 'center' }}
          justifyContent="space-between"
          spacing={2}
          sx={{ mb: 2.5 }}
        >
          <Box>
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 0.5 }}>
              <AdminPanelSettingsIcon color="primary" sx={{ fontSize: 28 }} />
              <Typography variant="h6" fontWeight={700}>
                منظومة الاستجابة والاحتواء الآلي (Enterprise Identity & Active Directory Remediation)
              </Typography>
              {loadingStatus ? <CircularProgress size={16} /> : <Chip label={status?.containment_enabled ? 'متصل ومفعل' : 'جاهز للمحاكاة'}
                size="small"
                color="success"
                icon={<CheckCircleIcon sx={{ fontSize: '16px !important' }} />}
                sx={{ fontWeight: 600 }}
              />}
            </Stack>
            <Typography variant="body2" color="text.secondary">
              عند وقوع الموظف في فخ التوعية (USB Baiting / BadUSB HID / Phishing)، يُطلق النظام استجابة فورية لحسابه المركزي في Active Directory أو Entra ID
            </Typography>
          </Box>

          <Button
            variant="contained"
            color="primary"
            startIcon={<PlayArrowIcon />}
            onClick={() => setTestModalOpen(true)}
            sx={{ fontWeight: 700, px: 2.5, py: 1 }}
          >
            اختبار الاستجابة الآلية لحساب موظف
          </Button>
        </Stack>

        {/* Integration Status Badges */}
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2.5 }}>
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
              <Typography variant="caption" fontWeight={700} color="text.primary">
                Active Directory (On-Premises)
              </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary">
              محرك PowerShell/LDAP الداخلي: جاهز لتطبيق <Chip label="pwdLastSet = 0" size="small" sx={{ height: 20, fontSize: 11 }} /> و <Chip label="FGPP 16-Chars" size="small" sx={{ height: 20, fontSize: 11 }} />
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
              <Typography variant="caption" fontWeight={700} color="text.primary">
                Microsoft Entra ID (Azure AD / M365)
              </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary">
              محرك Microsoft Graph API: جاهز لإلغاء الجلسات <Chip label="Revoke Sessions" size="small" sx={{ height: 20, fontSize: 11 }} /> وإجبار تغيير كلمة المرور
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
              <Typography variant="caption" fontWeight={700} color="text.primary">
                SOAR / SOC Integration
              </Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary">
              بث Webhook لحظي إلى مراكز العمليات (Microsoft Sentinel / Splunk / Wazuh) مع إحداثيات الهجمة
            </Typography>
          </Box>
        </Stack>

        <Alert severity="info" variant="outlined" sx={{ py: 0.75, fontSize: 13 }}>
          <strong>فجوة الاستجابة محلولة:</strong> السقوط في الفخ لا يُسجل فقط كـ "خطأ في التقرير"، بل يُترجم تلقائياً إلى أمر تنفيذي أمني يحمي حساب الموظف، ويجبره على تعيين كلمة مرور قوية ويطرده من أي جلسات مخترقة.
        </Alert>
      </CardContent>

      {/* Test / Execution Dialog */}
      <Dialog open={testModalOpen} onClose={() => setTestModalOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <LockResetIcon color="primary" />
            <Typography variant="h6" fontWeight={700}>
              محاكاة الاستجابة التقنية التلقائية في الدليل النشط
            </Typography>
          </Stack>
          <Chip label="Zero-Trust Enforcer" size="small" color="primary" />
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            حدد حساب الموظف المستهدف ونوع الهجمة لمحاكاة الاستجابة الأمنية الفورية التي ينفذها النظام في Active Directory / Entra ID فور حدوث الاختراق.
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

          <Box sx={{ mb: 2 }}>
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
              {triggering ? 'جاري تنفيذ أوامر الاستجابة في الدليل النشط...' : 'تفعيل الاستجابة الفورية والاحتواء للحساب الآن'}
            </Button>
          </Box>

          {lastReport && (
            <Box
              sx={{
                p: 2,
                borderRadius: 2,
                bgcolor: (t) => (t.palette.mode === 'dark' ? '#0a101d' : '#f0f7ff'),
                border: '1px solid',
                borderColor: 'primary.light',
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                <Typography variant="subtitle2" fontWeight={700} color="primary">
                  تقرير تنفيذ الاستجابة (Active Directory Execution Receipt):
                </Typography>
                <Chip label={lastReport.overall_status.toUpperCase()} color="success" size="small" />
              </Stack>

              <Typography variant="body2" sx={{ mb: 2, fontWeight: 600 }}>
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

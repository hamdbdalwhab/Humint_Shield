import { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Chip from '@mui/material/Chip';
import Alert from '@mui/material/Alert';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import LinearProgress from '@mui/material/LinearProgress';
import CircularProgress from '@mui/material/CircularProgress';
import UsbIcon from '@mui/icons-material/Usb';
import RefreshIcon from '@mui/icons-material/Refresh';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import SecurityIcon from '@mui/icons-material/Security';
import RadioButtonCheckedIcon from '@mui/icons-material/RadioButtonChecked';
import StorageIcon from '@mui/icons-material/Storage';
import KeyboardIcon from '@mui/icons-material/Keyboard';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DownloadIcon from '@mui/icons-material/Download';
import CloseIcon from '@mui/icons-material/Close';
import TerminalIcon from '@mui/icons-material/Terminal';
import MemoryIcon from '@mui/icons-material/Memory';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import IconButton from '@mui/material/IconButton';
import TextField from '@mui/material/TextField';
import Switch from '@mui/material/Switch';
import toast from 'react-hot-toast';

import { campaignsApi } from '@/api/endpoints';

interface DriveItem {
  drive: string;
  label: string;
  fs_type: string;
  is_removable: boolean;
  is_system?: boolean;
  type_name: string;
  free_gb: number;
  total_gb: number;
}

interface UsbDeploymentStationProps {
  campaignId: string;
  organizationId: string;
}

export function UsbDeploymentStation({ campaignId }: UsbDeploymentStationProps) {
  const [agentConnected, setAgentConnected] = useState(false);
  const [hostLabel, setHostLabel] = useState('');
  const [drives, setDrives] = useState<DriveItem[]>([]);
  const [selectedDrive, setSelectedDrive] = useState<string>('');
  const [loadingDrives, setLoadingDrives] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressStep, setProgressStep] = useState('');
  const [deployedFiles, setDeployedFiles] = useState<string[]>([]);
  const [deploymentSuccess, setDeploymentSuccess] = useState(false);
  const [includeIdentityTool, setIncludeIdentityTool] = useState(false);
  const [previewAssets, setPreviewAssets] = useState<any[]>([]);
  const [hidModalOpen, setHidModalOpen] = useState(false);
  const [hidTab, setHidTab] = useState(0);
  const [hidData, setHidData] = useState<any>(null);
  const [loadingHid, setLoadingHid] = useState(false);

  useEffect(() => {
    if (hidModalOpen && !hidData) {
      setLoadingHid(true);
      campaignsApi.generateHidScript(campaignId)
        .then((data) => {
          setHidData(data);
        })
        .catch((err) => {
          toast.error(err?.message || 'فشل جلب سكريبتات محاكاة لوحة المفاتيح');
        })
        .finally(() => {
          setLoadingHid(false);
        });
    }
  }, [hidModalOpen, campaignId, hidData]);

  function handleDownloadTextFile(text: string, filename: string) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
    toast.success(`تم تحميل ملف ${filename}`);
  }

  async function handleCopyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success('تم نسخ الكود إلى الحافظة بنجاح');
    } catch {
      toast.error('تعذر النسخ التلقائي');
    }
  }

  const wsRef = useRef<WebSocket | null>(null);

  function jsonAction(action: string, payload: Record<string, unknown> = {}) {
    return JSON.stringify({ action, ...payload });
  }

  // Preload test assets preview from campaign
  useEffect(() => {
    let active = true;
    campaignsApi.generateUsbTestPayload(campaignId)
      .then((data) => {
        if (active && data.assets) {
          setPreviewAssets(data.assets);
        }
      })
      .catch(() => {
        /* ignore */
      });
    return () => { active = false; };
  }, [campaignId]);

  function updateDrivesList(driveList: DriveItem[]) {
    setDrives(driveList);
    setLoadingDrives(false);

    setSelectedDrive((current) => {
      const stillExists = driveList.some((d) => d.drive === current && !d.is_system);
      if (stillExists) return current;

      const firstUsb = driveList.find((d) => d.is_removable && !d.is_system);
      if (firstUsb) return firstUsb.drive;

      const nonSystem = driveList.find((d) => !d.is_system);
      if (nonSystem) return nonSystem.drive;

      return '';
    });
  }

  // Hybrid connection: WebSocket (direct) + HTTP Loopback Bridge (for HTTPS/remote)
  useEffect(() => {
    let ws: WebSocket | null = null;
    let wsTimer: NodeJS.Timeout;
    let isWsWorking = false;

    // The console runs on the operator's own machine, so the server lists the
    // drives that are physically plugged in.  This is the primary source; the
    // optional companion agent is only a fallback.
    async function pollHttpBridge() {
      try {
        const res = await campaignsApi.usbDrives();
        setAgentConnected(true);
        setHostLabel(res.host);
        updateDrivesList(res.drives || []);
      } catch {
        try {
          const legacy = await campaignsApi.getUsbAgentStatus();
          if (legacy.online) {
            setAgentConnected(true);
            updateDrivesList(legacy.drives || []);
            return;
          }
        } catch {
          /* fall through to disconnected */
        }
        if (!isWsWorking) {
          setAgentConnected(false);
        }
      }
    }

    // Try WebSocket connection first
    function connectWs() {
      try {
        ws = new WebSocket('ws://127.0.0.1:8089');
        wsRef.current = ws;

        ws.onopen = () => {
          isWsWorking = true;
          setAgentConnected(true);
          ws?.send(jsonAction('list_drives'));
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'agent_connected' || data.type === 'drives_list') {
              updateDrivesList(data.drives || []);
            } else if (data.type === 'progress') {
              setProgress(data.percent || 0);
              setProgressStep(data.step || '');
            } else if (data.type === 'deployed_success') {
              setProgress(100);
              setProgressStep('تم التجهيز والحرق بنجاح!');
              setDeployedFiles(data.files || []);
              setDeploymentSuccess(true);
              setDeploying(false);
              toast.success(`تم نسخ ملفات التوعية إلى ${data.drive} بنجاح! الفلاشة جاهزة للاختبار الميداني.`);
            } else if (data.type === 'error') {
              setDeploying(false);
              toast.error(data.message || 'حدث خطأ أثناء كتابة محرك الـ USB');
            }
          } catch {
            /* ignore non-json */
          }
        };

        ws.onclose = () => {
          isWsWorking = false;
          wsRef.current = null;
          wsTimer = setTimeout(connectWs, 4000);
        };

        ws.onerror = () => {
          isWsWorking = false;
        };
      } catch {
        isWsWorking = false;
        wsTimer = setTimeout(connectWs, 4000);
      }
    }

    // Start WS and initial HTTP probe
    connectWs();
    pollHttpBridge();

    // Poll HTTP bridge every 3 seconds to ensure real-time USB drive detection even across HTTPS
    const pollInterval = setInterval(pollHttpBridge, 3000);

    return () => {
      clearTimeout(wsTimer);
      clearInterval(pollInterval);
      if (ws) {
        ws.close();
      }
    };
  }, []);

  async function handleRefreshDrives() {
    setLoadingDrives(true);
    try {
      const res = await campaignsApi.usbDrives();
      setAgentConnected(true);
      setHostLabel(res.host);
      updateDrivesList(res.drives || []);
      const removable = (res.drives || []).filter((d) => d.is_removable);
      toast.success(
        removable.length
          ? `تم العثور على ${removable.length} فلاشة متصلة`
          : 'لم يتم العثور على فلاشة. أدخل الفلاشة ثم اضغط تحديث.',
      );
    } catch {
      setAgentConnected(false);
      toast.error('تعذر قراءة قائمة الأقراص من الخادم المحلي');
    } finally {
      setLoadingDrives(false);
    }
  }

  async function handleDeployAssets() {
    if (!selectedDrive) {
      toast.error('يرجى اختيار فلاشة USB لتجهيزها');
      return;
    }

    // Preferred path: the local server generates the documents and writes them
    // directly onto the chosen stick (no companion agent needed).
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      try {
        setDeploying(true);
        setDeploymentSuccess(false);
        setProgress(30);
        setProgressStep(`جاري توليد الملفات ونسخها إلى ${selectedDrive}...`);
        const result = await campaignsApi.deployUsbArtifacts(
          campaignId,
          selectedDrive,
          true,
          includeIdentityTool,
        );
        setProgress(100);
        setProgressStep('تم النسخ بنجاح!');
        setDeployedFiles(result.files.map((f) => f.name));
        setDeploymentSuccess(true);
        setDeploying(false);
        toast.success(
          `تم نسخ ${result.files.length} ملف إلى ${result.drive} — الفلاشة جاهزة للاختبار الميداني.`,
        );
        return;
      } catch (err: any) {
        setDeploying(false);
        toast.error(err?.response?.data?.detail || err?.message || 'فشل نسخ الملفات إلى الفلاشة');
        return;
      }
    }

    try {
      setDeploying(true);
      setDeploymentSuccess(false);
      setProgress(15);
      setProgressStep('جاري توليد ملفات التوعية الآمنة من الخادم...');

      // 1. Fetch test payload assets from Backend
      const payloadData = await campaignsApi.generateUsbTestPayload(campaignId);
      if (!payloadData.assets || !payloadData.assets.length) {
        toast.error('لم يتم العثور على أصول المحاكاة في الخادم');
        setDeploying(false);
        return;
      }

      setProgress(40);
      setProgressStep(`جاري إرسال ${payloadData.assets.length} ملفات محاكاة إلى الوكيل المحلي...`);

      // 2. Send deploy command (via WS or HTTP loopback bridge)
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          jsonAction('deploy_test_assets', {
            drive: selectedDrive,
            assets: payloadData.assets,
          })
        );
      } else {
        setProgress(70);
        setProgressStep(`جاري نسخ أصول المحاكاة إلى المحرك ${selectedDrive}...`);
        const result = await campaignsApi.deployUsbAgentAssets({
          drive: selectedDrive,
          assets: payloadData.assets,
        });
        if (result.type === 'deployed_success') {
          setProgress(100);
          setProgressStep('تم التجهيز والحرق بنجاح!');
          setDeployedFiles(result.files || []);
          setDeploymentSuccess(true);
          setDeploying(false);
          toast.success(`تم نسخ ملفات التوعية إلى ${result.drive || selectedDrive} بنجاح! الفلاشة جاهزة للاختبار الميداني.`);
        } else {
          setDeploying(false);
          toast.error(result.message || 'حدث خطأ أثناء كتابة محرك الـ USB');
        }
      }
    } catch (err: any) {
      setDeploying(false);
      toast.error(err?.message || 'فشل توليد وتجهيز ملفات الـ USB');
    }
  }

  const removableDrives = drives.filter((d) => d.is_removable && !d.is_system);

  return (
    <Card
      sx={{
        mb: 3,
        border: '1px solid',
        borderColor: agentConnected ? 'rgba(0, 240, 255, 0.4)' : 'divider',
        bgcolor: 'background.paper',
        boxShadow: agentConnected ? '0 6px 25px rgba(0, 240, 255, 0.08)' : 'none',
      }}
    >
      <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
        {/* Header Stack */}
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          flexWrap="wrap"
          gap={1.5}
          sx={{ mb: 2 }}
        >
          <Stack direction="row" spacing={1.5} alignItems="center">
            <Box
              sx={{
                width: 44,
                height: 44,
                borderRadius: 2,
                bgcolor: 'primary.dark',
                color: 'primary.contrastText',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 0 15px rgba(0,240,255,0.3)',
              }}
            >
              <UsbIcon fontSize="medium" />
            </Box>
            <div>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>
                محطة تجهيز وحرق وسائط الـ USB الميدانية (Hardware Weaponization Station)
              </Typography>
              <Typography variant="caption" color="text.secondary">
                الربط المباشر مع منافذ الأجهزة لتسليح وتجهيز فلاشات التوعية الفيزيائية بنقرة واحدة
              </Typography>
            </div>
          </Stack>

          {/* Local Companion Agent Status Badge */}
          <Chip
            icon={agentConnected ? <CheckCircleIcon fontSize="small" /> : undefined}
            label={
              agentConnected
                ? `الخادم المحلي متصل${hostLabel ? ` · ${hostLabel}` : ''}`
                : 'تعذر قراءة الأقراص من الخادم المحلي'
            }
            color={agentConnected ? 'success' : 'error'}
            variant={agentConnected ? 'filled' : 'outlined'}
            sx={{ fontWeight: 800, fontSize: '0.8rem', px: 1 }}
          />
        </Stack>

        {/* Agent Offline Notice */}
        {!agentConnected ? (
          <Alert severity="warning" sx={{ mb: 2.5 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 0.5 }}>
              تعذر قراءة الأقراص من الخادم المحلي:
            </Typography>
            <Typography variant="body2" sx={{ fontSize: '0.83rem', mb: 1 }}>
              رصد الفلاشات يتم من الخادم المحلي مباشرة — لا حاجة لأي وكيل مساعد. إذا لم
              تظهر القائمة: تأكد أن الواجهة تُفتح من نفس الجهاز الذي يعمل عليه الخادم، ثم
              أدخل الفلاشة واضغط «تحديث».
            </Typography>
            <Box
              sx={{
                display: 'inline-block',
                bgcolor: 'rgba(0,0,0,0.2)',
                p: 1,
                borderRadius: 1,
                fontFamily: 'monospace',
                fontSize: '0.82rem',
                border: '1px solid rgba(255,255,255,0.1)',
                mb: 1.5,
              }}
            >
              GET /api/v1/campaigns/usb-drives
            </Box>
            <Box>
              <Button
                size="small"
                variant="outlined"
                onClick={handleRefreshDrives}
                disabled={loadingDrives}
              >
                إعادة محاولة قراءة الأقراص
              </Button>
            </Box>
          </Alert>
        ) : null}

        {/* Live Drive Hardware Status Banner */}
        {agentConnected ? (
          <Box sx={{ mb: 2.5 }}>
            {removableDrives.length > 0 ? (
              <Alert
                severity="success"
                icon={<RadioButtonCheckedIcon fontSize="inherit" />}
                sx={{ bgcolor: 'rgba(0,230,118,0.08)', border: '1px solid rgba(0,230,118,0.3)' }}
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                  🟢 تم التعرف على فلاشة USB متصلة بجهازك:
                </Typography>
                <Typography variant="body2" sx={{ fontSize: '0.84rem' }}>
                  المحرك: <strong>{removableDrives[0].drive}</strong> &nbsp; [{removableDrives[0].label}] — السعة: {removableDrives[0].total_gb} GB ({removableDrives[0].free_gb} GB متوفر) — {removableDrives[0].fs_type}. جاهز للتجهيز فوراً.
                </Typography>
              </Alert>
            ) : (
              <Alert
                severity="info"
                icon={<CircularProgress size={16} />}
                sx={{ bgcolor: 'rgba(0,240,255,0.05)', border: '1px solid rgba(0,240,255,0.2)' }}
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                  📡 جاري مراقبة منافذ الـ USB... بانتظار إدخال فلاشة:
                </Typography>
                <Typography variant="body2" sx={{ fontSize: '0.83rem' }}>
                  قم بتوصيل أي فلاشة USB بمنفذ الكمبيوتر؛ سيتم رصدها تلقائياً وإضافتها للقائمة فوراً دون الحاجة لتحديث الصفحة.
                </Typography>
              </Alert>
            )}
          </Box>
        ) : null}

        {/* Controls Section */}
        <Box sx={{ mt: 1 }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="center">
            {/* Drive Selection Dropdown */}
            <FormControl fullWidth size="small" sx={{ minWidth: 280, flex: 1 }}>
              <InputLabel id="select-usb-drive-label">محرك أقراص الـ USB المستهدف</InputLabel>
              <Select
                labelId="select-usb-drive-label"
                value={selectedDrive}
                label="محرك أقراص الـ USB المستهدف"
                onChange={(e) => setSelectedDrive(e.target.value)}
                disabled={!agentConnected || deploying}
              >
                {drives.map((d) => (
                  <MenuItem key={d.drive} value={d.drive} disabled={Boolean(d.is_system)}>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ width: '100%' }}>
                      <StorageIcon fontSize="small" color={d.is_removable ? 'success' : d.is_system ? 'disabled' : 'action'} />
                      <Typography variant="body2" sx={{ fontWeight: d.is_removable ? 700 : 400 }}>
                        {d.drive} &nbsp; [{d.label}] — {d.type_name} ({d.free_gb} GB / {d.total_gb} GB)
                      </Typography>
                      {d.is_removable ? (
                        <Chip label="USB Flash" size="small" color="success" sx={{ height: 20, fontSize: '0.7rem', ml: 'auto' }} />
                      ) : null}
                    </Stack>
                  </MenuItem>
                ))}
                {!drives.length ? (
                  <MenuItem value="" disabled>
                    لم يتم رصد أي محرك أقراص
                  </MenuItem>
                ) : null}
              </Select>
            </FormControl>

            {/* Refresh Drives Button */}
            <Button
              variant="outlined"
              size="medium"
              startIcon={loadingDrives ? <CircularProgress size={16} /> : <RefreshIcon />}
              onClick={handleRefreshDrives}
              disabled={!agentConnected || deploying}
              sx={{ minWidth: 130 }}
            >
              فحص المنافذ
            </Button>

            {/* Deploy & Arm Button */}
            <Button
              variant="contained"
              color="primary"
              size="medium"
              startIcon={deploying ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
              onClick={handleDeployAssets}
              disabled={!agentConnected || !selectedDrive || deploying}
              sx={{
                fontWeight: 800,
                px: 3,
                boxShadow: selectedDrive && agentConnected ? '0 0 15px rgba(0,240,255,0.4)' : 'none',
              }}
            >
              {deploying ? 'جاري النسخ والتجهيز...' : 'تجهيز وحرق ملفات الفلاشة'}
            </Button>
          </Stack>

          {/* Optional local identity collector */}
          <Box
            sx={{
              mt: 2,
              p: 1.5,
              borderRadius: 2,
              border: '1px dashed',
              borderColor: includeIdentityTool ? 'warning.main' : 'divider',
            }}
          >
            <FormControlLabel
              control={
                <Switch
                  checked={includeIdentityTool}
                  onChange={(event) => setIncludeIdentityTool(event.target.checked)}
                  disabled={deploying}
                />
              }
              label={
                <Typography variant="body2" sx={{ fontWeight: 800 }}>
                  إضافة أداة جمع اسم حساب Windows واسم الجهاز الحقيقي (اختياري)
                </Typography>
              }
            />
            <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
              تُنسخ أداة صغيرة بجوار ملف التوعية: <code>HUMINT_Identity_Check.cmd</code> +{' '}
              <code>HUMINT_Identity_Check.ps1</code>. صفحة HTML محجوبة عن قراءة اسم حساب النظام واسم
              الجهاز، وهذه الأداة تقرأهما وترسلهما إلى نفس سجل الفتح. لا تُشغَّل تلقائياً ولا تُعدّل شيئاً
              على جهاز الموظف.
            </Typography>
            {includeIdentityTool ? (
              <Alert severity="warning" sx={{ mt: 1.2, fontSize: '0.8rem' }}>
                <strong>تحذير SmartScreen المتوقع:</strong> عند أول تشغيل للأداة على جهاز الموظف قد يعرض
                Windows رسالة «Windows protected your PC» لأن الملف غير موقّع رقمياً. هذا سلوك طبيعي وليس
                دليلاً على خطر الملف؛ المسار هو <strong>More info</strong> ← <strong>Run anyway</strong>.
                إن منعت سياسة PowerShell تشغيل السكربت، شغّل ملف <code>.cmd</code> من موجّه الأوامر أو
                استخدم <code>Unblock-File</code>. لن يظهر اسم الحساب واسم الجهاز في نافذة التفاصيل إلا بعد
                تشغيل الأداة على الجهاز.
              </Alert>
            ) : null}
          </Box>

          {/* Preview of Assets to be Deployed */}
          {previewAssets.length > 0 ? (
            <Box
              sx={{
                mt: 2,
                p: 1.5,
                borderRadius: 2,
                bgcolor: 'rgba(255,255,255,0.02)',
                border: '1px solid rgba(255,255,255,0.06)',
              }}
            >
              <Typography variant="caption" sx={{ fontWeight: 800, color: 'text.secondary', display: 'block', mb: 0.8 }}>
                ملفات الطعم الفيزيائي التي سيتم كتابتها على الفلاشة ({previewAssets.length} ملفات محاكاة):
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap gap={1}>
                {previewAssets.map((asset) => (
                  <Chip
                    key={asset.filename}
                    label={`${asset.filename} (${asset.description || asset.type})`}
                    size="small"
                    variant="outlined"
                    color={asset.type === 'launcher' ? 'warning' : 'primary'}
                    sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}
                  />
                ))}
              </Stack>
            </Box>
          ) : null}

          {/* Safety Lock Notice */}
          <Alert severity="info" sx={{ mt: 2, fontSize: '0.8rem' }} icon={<SecurityIcon fontSize="inherit" />}>
            <strong>بروتوكول الأمان والامتثال المعتمد:</strong> الملفات المكتوبة مصممة كأدوات محاكاة حميدة بنسبة 100%، ولا تحدث أي تغييرات دائمة في النظام؛ عند قيام الموظف بتشغيلها، تقوم فقط برصد معرف محطة العمل وتوجيهه فوراً إلى مسار التوعية التفاعلي.
          </Alert>

          {/* Deployment Progress Bar */}
          {deploying ? (
            <Box sx={{ mt: 2.5 }}>
              <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.8 }}>
                <Typography variant="caption" sx={{ fontWeight: 700 }}>
                  {progressStep || 'جاري المعالجة والكتابة...'}
                </Typography>
                <Typography variant="caption" sx={{ fontWeight: 800 }}>
                  {progress}%
                </Typography>
              </Stack>
              <LinearProgress variant="determinate" value={progress} sx={{ height: 8, borderRadius: 1 }} />
            </Box>
          ) : null}

          {/* Success Summary */}
          {deploymentSuccess && deployedFiles.length ? (
            <Box
              sx={{
                mt: 2,
                p: 2,
                borderRadius: 2,
                bgcolor: 'rgba(0,230,118,0.06)',
                border: '1px solid rgba(0,230,118,0.3)',
              }}
            >
              <Typography variant="subtitle2" sx={{ fontWeight: 800, color: 'success.main', mb: 0.5 }}>
                ✓ تم تجهيز فلاشة الـ USB بنجاح على المحرك ({selectedDrive}):
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.82rem', mb: 1 }}>
                تم نسخ جميع ملفات السيناريو بنجاح. يمكنك الآن نزع الفلاشة وإسقاطها في الموقع الميداني المحدد لبدء تمرين المحاكاة.
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap gap={1}>
                {deployedFiles.map((f) => (
                  <Chip
                    key={f}
                    label={f}
                    size="small"
                    color="success"
                    variant="filled"
                    sx={{ fontFamily: 'monospace', fontSize: '0.75rem', fontWeight: 700 }}
                  />
                ))}
              </Stack>
            </Box>
          ) : null}
        </Box>
      </CardContent>
      {/* BadUSB HID Injection Modal */}
      <Dialog
        open={hidModalOpen}
        onClose={() => setHidModalOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            bgcolor: 'background.paper',
            border: '1px solid',
            borderColor: 'warning.dark',
            borderRadius: 2,
          },
        }}
      >
        <DialogTitle sx={{ m: 0, p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <Box
              sx={{
                width: 36,
                height: 36,
                borderRadius: 1.5,
                bgcolor: 'warning.dark',
                color: 'warning.contrastText',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <KeyboardIcon />
            </Box>
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>
                تجهيز محاكي لوحة المفاتيح الهجومي (BadUSB HID Emulator)
              </Typography>
              <Typography variant="caption" color="text.secondary">
                حقن الأوامر التوعوية تلقائياً عبر تجاوز قيود منع منافذ التخزين (Mass Storage Lockout)
              </Typography>
            </Box>
          </Stack>
          <IconButton onClick={() => setHidModalOpen(false)} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers sx={{ p: 2.5 }}>
          <Alert severity="warning" icon={<MemoryIcon />} sx={{ mb: 2.5, fontSize: '0.82rem' }}>
            <strong>طريقة عمل محاكاة الـ HID:</strong> يقوم هذا الوضع بمحاكاة جهاز لوحة مفاتيح حقيقي (Human Interface Device).
            بمجرد إدخال القطعة العتادية (مثل <strong>Raspberry Pi Pico</strong> أو <strong>Digispark</strong>) في حاسوب الهدف،
            يقوم العتاد بطباعة أمر توعوي خفي بسرعة فائقة لفتح نافذة التوعية وإرسال الهوية الحقيقية للجهاز إلى رادار المنظومة تلقائياً.
          </Alert>

          {loadingHid ? (
            <Box sx={{ py: 6, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
              <CircularProgress color="warning" />
            </Box>
          ) : hidData ? (
            <Box>
              <Tabs
                value={hidTab}
                onChange={(_, v) => setHidTab(v)}
                sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}
                textColor="inherit"
                indicatorColor="primary"
              >
                <Tab label="Raspberry Pi Pico (CircuitPython)" icon={<MemoryIcon fontSize="small" />} iconPosition="start" sx={{ fontWeight: 700 }} />
                <Tab label="DuckyScript (Rubber Ducky / Flipper Zero)" icon={<TerminalIcon fontSize="small" />} iconPosition="start" sx={{ fontWeight: 700 }} />
                <Tab label="Digispark ATtiny85 (Arduino .ino)" icon={<UsbIcon fontSize="small" />} iconPosition="start" sx={{ fontWeight: 700 }} />
              </Tabs>

              {/* Tab 0: Pico */}
              {hidTab === 0 ? (
                <Box>
                  <Typography variant="body2" sx={{ mb: 1, fontWeight: 700 }}>
                    خطوات التجهيز على Raspberry Pi Pico (تكلفة القطعة ~4$):
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                    1. ثبّت CircuitPython على الـ Pico، وتأكد من وجود مكتبة <code>adafruit_hid</code> داخل مجلد <code>lib/</code>.<br />
                    2. حمّل الكود أدناه واحفظه باسم <strong>code.py</strong> في المجلد الرئيسي لقرص <strong>CIRCUITPY</strong>.
                  </Typography>
                  <TextField
                    fullWidth
                    multiline
                    rows={9}
                    value={hidData.pico_circuitpython}
                    InputProps={{ readOnly: true, sx: { fontFamily: 'monospace', fontSize: '0.78rem', bgcolor: 'action.hover' } }}
                  />
                  <Stack direction="row" spacing={1.5} sx={{ mt: 1.5 }}>
                    <Button
                      variant="contained"
                      color="warning"
                      startIcon={<DownloadIcon />}
                      onClick={() => handleDownloadTextFile(hidData.pico_circuitpython, 'code.py')}
                      sx={{ fontWeight: 700 }}
                    >
                      تحميل ملف code.py
                    </Button>
                    <Button
                      variant="outlined"
                      startIcon={<ContentCopyIcon />}
                      onClick={() => handleCopyText(hidData.pico_circuitpython)}
                    >
                      نسخ الكود
                    </Button>
                  </Stack>
                </Box>
              ) : null}

              {/* Tab 1: DuckyScript */}
              {hidTab === 1 ? (
                <Box>
                  <Typography variant="body2" sx={{ mb: 1, fontWeight: 700 }}>
                    متوافق مع أجهزة: Hak5 Rubber Ducky, Flipper Zero (BadUSB), MalDuino, USB Ninja:
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                    احفظ النص البرمجي في ملف <strong>payload.dd</strong> وقم بتشغيله عبر جهاز الـ BadUSB المعتمد لديك.
                  </Typography>
                  <TextField
                    fullWidth
                    multiline
                    rows={9}
                    value={hidData.ducky_script}
                    InputProps={{ readOnly: true, sx: { fontFamily: 'monospace', fontSize: '0.78rem', bgcolor: 'action.hover' } }}
                  />
                  <Stack direction="row" spacing={1.5} sx={{ mt: 1.5 }}>
                    <Button
                      variant="contained"
                      color="warning"
                      startIcon={<DownloadIcon />}
                      onClick={() => handleDownloadTextFile(hidData.ducky_script, 'payload.dd')}
                      sx={{ fontWeight: 700 }}
                    >
                      تحميل ملف payload.dd
                    </Button>
                    <Button
                      variant="outlined"
                      startIcon={<ContentCopyIcon />}
                      onClick={() => handleCopyText(hidData.ducky_script)}
                    >
                      نسخ DuckyScript
                    </Button>
                  </Stack>
                </Box>
              ) : null}

              {/* Tab 2: Digispark */}
              {hidTab === 2 ? (
                <Box>
                  <Typography variant="body2" sx={{ mb: 1, fontWeight: 700 }}>
                    كود C++ لقطع Digispark ATtiny85 عبر Arduino IDE (تكلفة القطعة ~2$):
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
                    افتح برنامج Arduino IDE، واختر لوحة Digispark (Default - 16.5mhz)، ثم انسخ الكود وقم بحرقه (Upload).
                  </Typography>
                  <TextField
                    fullWidth
                    multiline
                    rows={9}
                    value={hidData.digispark_arduino}
                    InputProps={{ readOnly: true, sx: { fontFamily: 'monospace', fontSize: '0.78rem', bgcolor: 'action.hover' } }}
                  />
                  <Stack direction="row" spacing={1.5} sx={{ mt: 1.5 }}>
                    <Button
                      variant="contained"
                      color="warning"
                      startIcon={<DownloadIcon />}
                      onClick={() => handleDownloadTextFile(hidData.digispark_arduino, 'digispark_sketch.ino')}
                      sx={{ fontWeight: 700 }}
                    >
                      تحميل ملف sketch.ino
                    </Button>
                    <Button
                      variant="outlined"
                      startIcon={<ContentCopyIcon />}
                      onClick={() => handleCopyText(hidData.digispark_arduino)}
                    >
                      نسخ الكود
                    </Button>
                  </Stack>
                </Box>
              ) : null}
            </Box>
          ) : (
            <Alert severity="error">تعذر تحميل بيانات المحاكاة</Alert>
          )}
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setHidModalOpen(false)}>إغلاق</Button>
        </DialogActions>
      </Dialog>

    </Card>
  );
}

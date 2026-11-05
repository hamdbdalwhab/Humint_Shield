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
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import LinearProgress from '@mui/material/LinearProgress';
import CircularProgress from '@mui/material/CircularProgress';
import UsbIcon from '@mui/icons-material/Usb';
import RefreshIcon from '@mui/icons-material/Refresh';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import DownloadIcon from '@mui/icons-material/Download';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import SecurityIcon from '@mui/icons-material/Security';
import toast from 'react-hot-toast';

import { campaignsApi } from '@/api/endpoints';

interface DriveItem {
  drive: string;
  label: string;
  fs_type: string;
  is_removable: boolean;
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
  const [drives, setDrives] = useState<DriveItem[]>([]);
  const [selectedDrive, setSelectedDrive] = useState<string>('');
  const [loadingDrives, setLoadingDrives] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressStep, setProgressStep] = useState('');
  const [deployedFiles, setDeployedFiles] = useState<string[]>([]);
  const [deploymentSuccess, setDeploymentSuccess] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);

  // Connect to Local Deployment Agent on ws://127.0.0.1:8089
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: NodeJS.Timeout;

    function connect() {
      try {
        ws = new WebSocket('ws://127.0.0.1:8089');
        wsRef.current = ws;

        ws.onopen = () => {
          setAgentConnected(true);
          // Request connected drives immediately
          ws?.send(jsonAction('list_drives'));
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'drives_list') {
              setDrives(data.drives || []);
              setLoadingDrives(false);
              // Auto-select first removable drive if available
              const removable = (data.drives || []).find((d: DriveItem) => d.is_removable);
              if (removable && !selectedDrive) {
                setSelectedDrive(removable.drive);
              } else if (data.drives?.length && !selectedDrive) {
                setSelectedDrive(data.drives[0].drive);
              }
            } else if (data.type === 'progress') {
              setProgress(data.percent || 0);
              setProgressStep(data.step || '');
            } else if (data.type === 'deployed_success') {
              setProgress(100);
              setProgressStep('تم التجهيز بنجاح!');
              setDeployedFiles(data.files || []);
              setDeploymentSuccess(true);
              setDeploying(false);
              toast.success(`تم نسخ ملفات التوعية إلى ${data.drive} بنجاح!`);
            } else if (data.type === 'error') {
              setDeploying(false);
              toast.error(data.message || 'حدث خطأ أثناء الاتصال بالوكيل المحلي');
            }
          } catch {
            /* ignore non-json */
          }
        };

        ws.onclose = () => {
          setAgentConnected(false);
          wsRef.current = null;
          // Retry connection every 4 seconds
          timer = setTimeout(connect, 4000);
        };

        ws.onerror = () => {
          setAgentConnected(false);
        };
      } catch {
        setAgentConnected(false);
        timer = setTimeout(connect, 4000);
      }
    }

    connect();

    return () => {
      clearTimeout(timer);
      if (ws) {
        ws.close();
      }
    };
  }, []);

  function jsonAction(action: string, payload: Record<string, unknown> = {}) {
    return JSON.stringify({ action, ...payload });
  }

  function handleRefreshDrives() {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      toast.error('الوكيل المحلي غير متصل. يرجى تشغيل deployment_agent.py');
      return;
    }
    setLoadingDrives(true);
    wsRef.current.send(jsonAction('list_drives'));
  }

  async function handleDeployAssets() {
    if (!selectedDrive) {
      toast.error('يرجى اختيار محرك أقراص USB لتجهيزه');
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      toast.error('الوكيل المحلي غير متصل. يرجى تشغيل deployment_agent.py');
      return;
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
      setProgressStep(`جاري إرسال ${payloadData.assets.length} ملفات إلى الوكيل المحلي...`);

      // 2. Send deploy command to Local Companion Agent via WebSocket
      wsRef.current.send(
        jsonAction('deploy_test_assets', {
          drive: selectedDrive,
          assets: payloadData.assets,
        })
      );
    } catch (err: any) {
      setDeploying(false);
      toast.error(err?.message || 'فشل توليد وتجهيز ملفات الـ USB');
    }
  }

  return (
    <Card
      sx={{
        mb: 3,
        border: '1px solid',
        borderColor: agentConnected ? 'rgba(0, 240, 255, 0.3)' : 'divider',
        bgcolor: 'background.paper',
        boxShadow: agentConnected ? '0 4px 20px rgba(0, 240, 255, 0.06)' : 'none',
      }}
    >
      <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
        {/* Header Stack */}
        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1.5} sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <Box
              sx={{
                width: 42,
                height: 42,
                borderRadius: 2,
                bgcolor: 'primary.dark',
                color: 'primary.contrastText',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <UsbIcon fontSize="medium" />
            </Box>
            <div>
              <Typography variant="h6" sx={{ fontWeight: 800 }}>
                محطة تجهيز وتوزيع وسائط الـ USB (Endpoint Deployment Station)
              </Typography>
              <Typography variant="caption" color="text.secondary">
                تجهيز ونشر ملفات التوعية الميدانية واختبار استجابة الأجهزة لنواقل الاختراق الفيزيائية
              </Typography>
            </div>
          </Stack>

          {/* Local Companion Agent Status Badge */}
          <Chip
            icon={agentConnected ? <CheckCircleIcon fontSize="small" /> : undefined}
            label={agentConnected ? 'الوكيل المحلي متصل (ws://127.0.0.1:8089)' : 'الوكيل المحلي غير متصل'}
            color={agentConnected ? 'success' : 'error'}
            variant={agentConnected ? 'filled' : 'outlined'}
            sx={{ fontWeight: 800, fontSize: '0.78rem' }}
          />
        </Stack>

        {/* Agent Offline Notice & Download Instructions */}
        {!agentConnected ? (
          <Alert severity="warning" sx={{ mb: 2.5 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 0.5 }}>
              وكيل النشر المحلي (Local Companion App) غير نشط على جهازك:
            </Typography>
            <Typography variant="body2" sx={{ fontSize: '0.82rem', mb: 1 }}>
              نظراً لعزل المتصفح (Browser Sandbox) وحماية منافذ الأجهزة، تتطلب الكتابة التلقائية على أقراص الـ USB تشغيل الوكيل المساعد المحلي.
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <Button
                size="small"
                variant="contained"
                color="warning"
                startIcon={<DownloadIcon />}
                onClick={() => {
                  window.open('/api/v1/campaigns/companion-agent-download', '_blank');
                }}
              >
                تشغيل الوكيل المحلي (deployment_agent.py)
              </Button>
              <Typography variant="caption" color="text.secondary">
                الأمر المباشر: <code>python deployment_agent.py</code>
              </Typography>
            </Stack>
          </Alert>
        ) : null}

        {/* Wizard Controls */}
        <Box sx={{ mt: 2 }}>
          <GridWrapper>
            {/* Step 1: Select Target Drive */}
            <Box sx={{ flex: 1, minWidth: 260 }}>
              <FormControl fullWidth size="small">
                <InputLabel id="select-usb-drive-label">محرك أقراص الـ USB المستهدف</InputLabel>
                <Select
                  labelId="select-usb-drive-label"
                  value={selectedDrive}
                  label="محرك أقراص الـ USB المستهدف"
                  onChange={(e) => setSelectedDrive(e.target.value)}
                  disabled={!agentConnected || deploying}
                >
                  {drives.map((d) => (
                    <MenuItem key={d.drive} value={d.drive}>
                      <strong>{d.drive}</strong> &nbsp; [{d.label}] — {d.type_name} ({d.free_gb} GB متوفر)
                    </MenuItem>
                  ))}
                  {!drives.length ? (
                    <MenuItem value="" disabled>
                      لم يتم رصد أي محرك أقراص متصل
                    </MenuItem>
                  ) : null}
                </Select>
              </FormControl>
            </Box>

            {/* Refresh Drives Button */}
            <Button
              variant="outlined"
              size="medium"
              startIcon={loadingDrives ? <CircularProgress size={16} /> : <RefreshIcon />}
              onClick={handleRefreshDrives}
              disabled={!agentConnected || deploying}
              sx={{ minWidth: 120 }}
            >
              تحديث الأقراص
            </Button>

            {/* Step 2: Click to Deploy & Weaponize */}
            <Button
              variant="contained"
              color="primary"
              size="medium"
              startIcon={deploying ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
              onClick={handleDeployAssets}
              disabled={!agentConnected || !selectedDrive || deploying}
              sx={{ fontWeight: 800, px: 3 }}
            >
              {deploying ? 'جاري التجهيز...' : 'تثبيت ملفات المحاكاة على الـ USB'}
            </Button>
          </GridWrapper>

          {/* Safety Notice */}
          <Alert severity="info" sx={{ mt: 2, fontSize: '0.8rem' }} icon={<SecurityIcon fontSize="inherit" />}>
            <strong>تأكيد الأمان والموثوقية:</strong> ملفات المحاكاة التي يتم نسخها (Company_Security_Notice.url، فحص_الوعي_الأمني.bat، واقرأني.txt) مصممة كأدوات توعية حميدة فقط؛ عند فتحها تقوم بتسجيل الاستجابة وتوجيه المستخدم مباشرة لبوابة التوعية التفاعلية دون أي ضرر أو تعديل على النظام.
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
            <Box sx={{ mt: 2, p: 1.5, borderRadius: 2, bgcolor: 'action.hover', border: '1px solid rgba(0,230,118,0.3)' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, color: 'success.main', mb: 0.5 }}>
                ✓ تم تجهيز محرك الـ USB بنجاح ({selectedDrive}):
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                تم نسخ الملفات الآتية بنجاح وهي جاهزة لاختبار التوعية الميدانية:
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap">
                {deployedFiles.map((f) => (
                  <Chip key={f} label={f} size="small" color="success" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }} />
                ))}
              </Stack>
            </Box>
          ) : null}
        </Box>
      </CardContent>
    </Card>
  );
}

function GridWrapper({ children }: { children: React.ReactNode }) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 1.5,
        alignItems: 'center',
      }}
    >
      {children}
    </Box>
  );
}

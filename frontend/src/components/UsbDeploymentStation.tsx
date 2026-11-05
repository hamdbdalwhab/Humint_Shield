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
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import SecurityIcon from '@mui/icons-material/Security';
import RadioButtonCheckedIcon from '@mui/icons-material/RadioButtonChecked';
import StorageIcon from '@mui/icons-material/Storage';
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
  const [drives, setDrives] = useState<DriveItem[]>([]);
  const [selectedDrive, setSelectedDrive] = useState<string>('');
  const [loadingDrives, setLoadingDrives] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressStep, setProgressStep] = useState('');
  const [deployedFiles, setDeployedFiles] = useState<string[]>([]);
  const [deploymentSuccess, setDeploymentSuccess] = useState(false);
  const [previewAssets, setPreviewAssets] = useState<any[]>([]);

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

  // Connect to Local Companion Agent on ws://127.0.0.1:8089
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: NodeJS.Timeout;
    let pollInterval: NodeJS.Timeout;

    function connect() {
      try {
        ws = new WebSocket('ws://127.0.0.1:8089');
        wsRef.current = ws;

        ws.onopen = () => {
          setAgentConnected(true);
          // Query drives immediately
          ws?.send(jsonAction('list_drives'));

          // Continuous live polling every 2.5 seconds to capture USB insertions instantly
          pollInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(jsonAction('list_drives'));
            }
          }, 2500);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'agent_connected' || data.type === 'drives_list') {
              const driveList: DriveItem[] = data.drives || [];
              setDrives(driveList);
              setLoadingDrives(false);

              // Auto-select removable USB drive if found and nothing selected or current selection invalid
              setSelectedDrive((current) => {
                const stillExists = driveList.some((d) => d.drive === current && !d.is_system);
                if (stillExists) return current;

                const firstUsb = driveList.find((d) => d.is_removable && !d.is_system);
                if (firstUsb) return firstUsb.drive;

                const nonSystem = driveList.find((d) => !d.is_system);
                if (nonSystem) return nonSystem.drive;

                return '';
              });
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
          setAgentConnected(false);
          wsRef.current = null;
          clearInterval(pollInterval);
          // Retry connection every 3 seconds
          timer = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          setAgentConnected(false);
        };
      } catch {
        setAgentConnected(false);
        timer = setTimeout(connect, 3000);
      }
    }

    connect();

    return () => {
      clearTimeout(timer);
      clearInterval(pollInterval);
      if (ws) {
        ws.close();
      }
    };
  }, []);

  function handleRefreshDrives() {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      toast.error('الوكيل المحلي غير متصل. يرجى تشغيل start_usb_agent.bat');
      return;
    }
    setLoadingDrives(true);
    wsRef.current.send(jsonAction('list_drives'));
    toast.success('جاري فحص منافذ الـ USB...');
  }

  async function handleDeployAssets() {
    if (!selectedDrive) {
      toast.error('يرجى اختيار محرك أقراص USB لتجهيزه');
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      toast.error('الوكيل المحلي غير متصل. يرجى تشغيل start_usb_agent.bat');
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
      setProgressStep(`جاري إرسال ${payloadData.assets.length} ملفات محاكاة إلى الوكيل المحلي...`);

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
            label={agentConnected ? 'الوكيل المحلي متصل (ws://127.0.0.1:8089)' : 'الوكيل المحلي غير متصل'}
            color={agentConnected ? 'success' : 'error'}
            variant={agentConnected ? 'filled' : 'outlined'}
            sx={{ fontWeight: 800, fontSize: '0.8rem', px: 1 }}
          />
        </Stack>

        {/* Agent Offline Notice */}
        {!agentConnected ? (
          <Alert severity="warning" sx={{ mb: 2.5 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 0.5 }}>
              وكيل النشر المساعد (Local Companion Agent) غير مشغل حالياً:
            </Typography>
            <Typography variant="body2" sx={{ fontSize: '0.83rem', mb: 1 }}>
              لتمكين رصد منافذ الـ USB والكتابة التلقائية المباشرة، يرجى تشغيل المشغل التلقائي المرفق بنقرة واحدة:
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
              }}
            >
              start_usb_agent.bat &nbsp; (أو تنفيذ: python deployment_agent.py)
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
    </Card>
  );
}

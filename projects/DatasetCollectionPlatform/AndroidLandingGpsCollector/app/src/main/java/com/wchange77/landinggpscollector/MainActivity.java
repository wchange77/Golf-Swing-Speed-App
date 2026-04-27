package com.wchange77.landinggpscollector;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Criteria;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

public class MainActivity extends Activity {
    private static final int REQUEST_LOCATION = 1001;
    private static final int REQUEST_EXPORT = 1002;

    private EditText sessionNameInput;
    private TextView statusText;
    private TextView historyText;
    private Location latestLocation;
    private LocationManager locationManager;

    private final LocationListener listener = new LocationListener() {
        @Override
        public void onLocationChanged(Location location) {
            latestLocation = location;
            updateStatus();
        }

        @Override
        public void onProviderEnabled(String provider) {
            updateStatus();
        }

        @Override
        public void onProviderDisabled(String provider) {
            updateStatus();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        locationManager = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        buildUi();
        requestLocationPermission();
        refreshHistory();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (hasFineLocation()) {
            locationManager.removeUpdates(listener);
        }
    }

    private void buildUi() {
        ScrollView scrollView = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(20);
        root.setPadding(padding, padding, padding, padding);
        scrollView.addView(root);

        TextView title = new TextView(this);
        title.setText("落球点 GPS 记录");
        title.setTextSize(24);
        title.setTextColor(0xFF111111);
        root.addView(title);

        sessionNameInput = new EditText(this);
        sessionNameInput.setHint("会话名称，例如 1");
        sessionNameInput.setSingleLine(true);
        sessionNameInput.setText("1");
        root.addView(sessionNameInput);

        statusText = new TextView(this);
        statusText.setTextSize(15);
        statusText.setPadding(0, dp(12), 0, dp(12));
        root.addView(statusText);

        Button refreshButton = new Button(this);
        refreshButton.setText("刷新高精度 GPS");
        refreshButton.setOnClickListener(v -> startLocationUpdates());
        root.addView(refreshButton);

        Button recordButton = new Button(this);
        recordButton.setText("记录落球点");
        recordButton.setOnClickListener(v -> recordLandingPoint());
        root.addView(recordButton);

        Button exportButton = new Button(this);
        exportButton.setText("导出 JSONL");
        exportButton.setOnClickListener(v -> exportJsonl());
        root.addView(exportButton);

        historyText = new TextView(this);
        historyText.setTextSize(14);
        historyText.setPadding(0, dp(16), 0, 0);
        root.addView(historyText);

        setContentView(scrollView);
    }

    private void requestLocationPermission() {
        if (!hasFineLocation()) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, REQUEST_LOCATION);
            statusText.setText("等待定位权限");
            return;
        }
        startLocationUpdates();
    }

    private void startLocationUpdates() {
        if (!hasFineLocation()) {
            requestLocationPermission();
            return;
        }
        try {
            Criteria criteria = new Criteria();
            criteria.setAccuracy(Criteria.ACCURACY_FINE);
            criteria.setAltitudeRequired(true);
            criteria.setSpeedRequired(false);
            criteria.setBearingRequired(false);
            String provider = locationManager.getBestProvider(criteria, true);
            if (provider == null) {
                provider = LocationManager.GPS_PROVIDER;
            }
            Location last = locationManager.getLastKnownLocation(provider);
            if (last != null) {
                latestLocation = last;
            }
            locationManager.requestLocationUpdates(provider, 1000L, 0f, listener, Looper.getMainLooper());
            updateStatus();
        } catch (SecurityException ex) {
            statusText.setText("定位权限未开启");
        }
    }

    private void updateStatus() {
        if (!hasFineLocation()) {
            statusText.setText("定位权限未开启");
            return;
        }
        boolean gpsEnabled = locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER);
        if (!gpsEnabled) {
            statusText.setText("GPS 未开启，请在系统设置中打开高精度定位");
            startActivity(new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS));
            return;
        }
        if (latestLocation == null) {
            statusText.setText("正在等待高精度 GPS");
            return;
        }
        statusText.setText(String.format(
                Locale.US,
                "当前 GPS: %.7f, %.7f\n精度: %.1f 米  海拔: %.1f 米\n设备: %s",
                latestLocation.getLatitude(),
                latestLocation.getLongitude(),
                latestLocation.getAccuracy(),
                latestLocation.hasAltitude() ? latestLocation.getAltitude() : 0.0,
                deviceName()
        ));
    }

    private void recordLandingPoint() {
        String sessionName = sessionNameInput.getText().toString().trim();
        if (sessionName.isEmpty()) {
            statusText.setText("会话名称不能为空");
            return;
        }
        if (latestLocation == null) {
            statusText.setText("还没有可用 GPS，请先刷新定位");
            startLocationUpdates();
            return;
        }
        try {
            JSONObject location = locationJson(latestLocation, "android_landing_point");
            JSONObject reference = new JSONObject();
            reference.put("source", "android_landing_point");
            reference.put("device", deviceName());
            reference.put("capturedAt", nowIso8601());
            reference.put("clubSpeedMph", JSONObject.NULL);
            reference.put("ballSpeedMph", JSONObject.NULL);
            reference.put("carryDistanceMeters", JSONObject.NULL);
            reference.put("totalDistanceMeters", JSONObject.NULL);
            reference.put("launchAngleDegrees", JSONObject.NULL);
            reference.put("spinRateRpm", JSONObject.NULL);
            reference.put("landingLocation", location);
            reference.put("notes", "小米旗舰机记录落球点 GPS");

            JSONArray measurements = new JSONArray();
            measurements.put(reference);

            JSONObject record = new JSONObject();
            record.put("sessionName", sessionName);
            record.put("capturedAt", nowIso8601());
            record.put("source", "android_landing_point");
            record.put("device", deviceName());
            record.put("landingLocation", location);
            record.put("referenceMeasurements", measurements);

            try (FileOutputStream out = new FileOutputStream(dataFile(), true)) {
                out.write(record.toString().getBytes(StandardCharsets.UTF_8));
                out.write('\n');
            }
            refreshHistory();
            statusText.setText("已记录落球点 GPS");
        } catch (Exception ex) {
            statusText.setText("记录失败: " + ex.getMessage());
        }
    }

    private JSONObject locationJson(Location location, String source) throws Exception {
        JSONObject json = new JSONObject();
        json.put("latitude", location.getLatitude());
        json.put("longitude", location.getLongitude());
        json.put("horizontalAccuracyMeters", location.hasAccuracy() ? location.getAccuracy() : 0.0);
        json.put("altitudeMeters", location.hasAltitude() ? location.getAltitude() : JSONObject.NULL);
        json.put("verticalAccuracyMeters", verticalAccuracy(location));
        json.put("capturedAt", nowIso8601());
        json.put("source", source);
        return json;
    }

    private Object verticalAccuracy(Location location) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && location.hasVerticalAccuracy()) {
            return location.getVerticalAccuracyMeters();
        }
        return JSONObject.NULL;
    }

    private void exportJsonl() {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/json");
        intent.putExtra(Intent.EXTRA_TITLE, "landing_points.jsonl");
        startActivityForResult(intent, REQUEST_EXPORT);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_EXPORT || resultCode != RESULT_OK || data == null) {
            return;
        }
        Uri uri = data.getData();
        if (uri == null) {
            return;
        }
        try (OutputStream out = getContentResolver().openOutputStream(uri);
             FileInputStream in = new FileInputStream(dataFile())) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            statusText.setText("已导出 landing_points.jsonl");
        } catch (Exception ex) {
            statusText.setText("导出失败: " + ex.getMessage());
        }
    }

    private void refreshHistory() {
        File file = dataFile();
        if (!file.exists()) {
            historyText.setText("暂无落球点记录");
            return;
        }
        StringBuilder builder = new StringBuilder("历史记录:\n");
        int count = 0;
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(new FileInputStream(file), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) {
                    continue;
                }
                count++;
                JSONObject object = new JSONObject(line);
                JSONObject location = object.getJSONObject("landingLocation");
                builder.append(count)
                        .append(". ")
                        .append(object.optString("sessionName"))
                        .append("  ")
                        .append(String.format(Locale.US, "%.6f, %.6f", location.getDouble("latitude"), location.getDouble("longitude")))
                        .append("  ")
                        .append(object.optString("capturedAt"))
                        .append('\n');
            }
        } catch (Exception ex) {
            builder.append("读取失败: ").append(ex.getMessage());
        }
        historyText.setText(count == 0 ? "暂无落球点记录" : builder.toString());
    }

    private File dataFile() {
        return new File(getFilesDir(), "landing_points.jsonl");
    }

    private boolean hasFineLocation() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private String nowIso8601() {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date());
    }

    private String deviceName() {
        return Build.MANUFACTURER + " " + Build.MODEL;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_LOCATION && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startLocationUpdates();
        } else {
            statusText.setText("定位权限被拒绝，无法记录落球点");
        }
    }
}

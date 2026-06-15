package com.sanskriti.aiscanner;

import android.Manifest;
import android.app.DownloadManager;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.DownloadListener;
import android.webkit.WebView;
import android.widget.Toast;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private static final int STORAGE_PERMISSION_CODE = 101;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        
        // Step 1: Check and request device storage permissions right when app launches
        checkStoragePermission();

        // Step 2: Set up a listener to intercept the file download from Hugging Face
        this.bridge.getWebView().post(new Runnable() {
            @Override
            public void run() {
                WebView webView = bridge.getWebView();
                webView.getSettings().setJavaScriptEnabled(true);
                
                webView.setDownloadListener(new DownloadListener() {
                    @Override
                    public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimetype, long contentLength) {
                        
                        // Hand off the standard URL to Android's Native Download Manager System
                        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                        request.setMimeType(mimetype);
                        request.addRequestHeader("User-Agent", userAgent);
                        request.setDescription("Downloading Student Marks Excel Sheet...");
                        request.setTitle("compiled_student_marks.xlsx");
                        
                        // Ensure a completion banner notification pops up on the phone status tray
                        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                        request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "compiled_student_marks.xlsx");
                        
                        DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                        if (dm != null) {
                            dm.enqueue(request);
                            Toast.makeText(MainActivity.this, "Download started! File will save to Downloads Folder.", Toast.LENGTH_LONG).show();
                        }
                    }
                });
            }
        });
    }

    private void checkStoragePermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, STORAGE_PERMISSION_CODE);
            }
        }
    }
}

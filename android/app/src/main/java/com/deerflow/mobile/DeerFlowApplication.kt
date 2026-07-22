package com.deerflow.mobile

import android.app.Application
import android.webkit.CookieManager

class DeerFlowApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        CookieManager.getInstance().setAcceptCookie(true)
    }
}

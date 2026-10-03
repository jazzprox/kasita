package cw.jazzproxy.kasita

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.view.View
import android.widget.RemoteViews
import es.antonborri.home_widget.HomeWidgetLaunchIntent
import es.antonborri.home_widget.HomeWidgetPlugin
import es.antonborri.home_widget.HomeWidgetProvider
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Home-screen widget: the open shopping list (tap an item to tick it off), a + that
 * opens the list in the app, and what to use soon.
 *
 * Android calls onUpdate every 30 minutes (updatePeriodMillis). The widget first
 * draws what it has, then fetches fresh data from Kasita in the background with
 * its own read-only key (created by the app) and redraws. That key may do one
 * write: tick an item off. A tick made without signal is kept and sent later.
 */
class KasitaWidgetProvider : HomeWidgetProvider() {
    companion object {
        const val ACTION_TICK = "cw.jazzproxy.kasita.WIDGET_TICK"
        const val EXTRA_ITEM = "item_id"
        private const val PENDING = "pending_ticks" // item ids ticked here, not yet sent

        /** Redraw every Kasita widget (after a tick, or when the app saved new data). */
        fun refreshAll(context: Context) {
            val mgr = AppWidgetManager.getInstance(context)
            val ids = mgr.getAppWidgetIds(ComponentName(context, KasitaWidgetProvider::class.java))
            if (ids.isEmpty()) return
            draw(context, mgr, ids, HomeWidgetPlugin.getData(context))
            mgr.notifyAppWidgetViewDataChanged(ids, R.id.widget_list)
        }

        fun items(widgetData: SharedPreferences): JSONArray =
            try {
                JSONArray(widgetData.getString("items_json", "[]"))
            } catch (e: Exception) {
                JSONArray()
            }

        private fun draw(
            context: Context,
            appWidgetManager: AppWidgetManager,
            appWidgetIds: IntArray,
            widgetData: SharedPreferences,
        ) {
            val list = items(widgetData)
            val hasList = widgetData.contains("items_json")
            for (id in appWidgetIds) {
                val views = RemoteViews(context.packageName, R.layout.kasita_widget).apply {
                    setTextViewText(
                        R.id.widget_shopping_title,
                        if (hasList) "Shopping list (${list.length()})"
                        else widgetData.getString("shopping_title", "Shopping list"),
                    )
                    setTextViewText(R.id.widget_soon, widgetData.getString("soon", ""))
                    // the list, served by KasitaWidgetService; the text fallback for the very first draw
                    val svc = Intent(context, KasitaWidgetService::class.java).apply {
                        putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
                        data = Uri.parse("kasita-widget://$id") // one adapter per widget
                    }
                    @Suppress("DEPRECATION")
                    setRemoteAdapter(R.id.widget_list, svc)
                    setEmptyView(R.id.widget_list, R.id.widget_empty)
                    setTextViewText(
                        R.id.widget_empty,
                        when {
                            !hasList -> widgetData.getString("shopping", "Open Kasita once to fill this in")
                            list.length() == 0 -> "Nothing to buy"
                            else -> ""
                        },
                    )
                    val tick = Intent(context, KasitaWidgetProvider::class.java).apply { action = ACTION_TICK }
                    val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                        (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                    setPendingIntentTemplate(R.id.widget_list, PendingIntent.getBroadcast(context, 0, tick, flags))
                    setOnClickPendingIntent(
                        R.id.widget_add,
                        HomeWidgetLaunchIntent.getActivity(
                            context, MainActivity::class.java, Uri.parse("kasita://shopping"),
                        ),
                    )
                    setOnClickPendingIntent(
                        R.id.widget_shopping_title,
                        HomeWidgetLaunchIntent.getActivity(
                            context, MainActivity::class.java, Uri.parse("kasita://shopping"),
                        ),
                    )
                    setOnClickPendingIntent(
                        R.id.widget_soon,
                        HomeWidgetLaunchIntent.getActivity(context, MainActivity::class.java),
                    )
                    setViewVisibility(R.id.widget_soon, if (widgetData.getString("soon", "").isNullOrEmpty()) View.GONE else View.VISIBLE)
                }
                appWidgetManager.updateAppWidget(id, views)
            }
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == ACTION_TICK) {
            val itemId = intent.getStringExtra(EXTRA_ITEM) ?: return
            val data = HomeWidgetPlugin.getData(context)
            // gone from the widget right away; sent in the background, kept for later when offline
            val left = JSONArray()
            val all = items(data)
            for (i in 0 until all.length()) {
                val o = all.getJSONObject(i)
                if (o.optString("id") != itemId) left.put(o)
            }
            val pending = (data.getString(PENDING, "") ?: "").split(',').filter { it.isNotEmpty() }.toMutableSet()
            pending.add(itemId)
            data.edit().putString("items_json", left.toString()).putString(PENDING, pending.joinToString(",")).apply()
            refreshAll(context)
            val result = goAsync()
            Thread {
                try {
                    sendPending(data)
                } finally {
                    result.finish()
                }
            }.start()
            return
        }
        super.onReceive(context, intent)
    }

    /** Send ticks made on the widget; whatever fails stays queued. */
    private fun sendPending(data: SharedPreferences) {
        val server = data.getString("kasita_server", null)
        val hid = data.getString("kasita_hid", null)
        val key = data.getString("kasita_key", null)
        if (server.isNullOrEmpty() || hid.isNullOrEmpty() || key.isNullOrEmpty()) return
        val pending = (data.getString(PENDING, "") ?: "").split(',').filter { it.isNotEmpty() }
        val failed = mutableListOf<String>()
        for (id in pending) {
            try {
                val conn = URL("${server.trimEnd('/')}/api/households/$hid/widget/tick/$id")
                    .openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.connectTimeout = 8000
                conn.readTimeout = 8000
                conn.setRequestProperty("X-Api-Key", key)
                val code = conn.responseCode
                conn.disconnect()
                // 404: deleted on another phone meanwhile; nothing left to tick
                if (code != 200 && code != 404) failed.add(id)
            } catch (e: Exception) {
                failed.add(id)
            }
        }
        // ticks made while this ran are kept too
        val now = (data.getString(PENDING, "") ?: "").split(',').filter { it.isNotEmpty() }
        val keep = (failed + now.filter { it !in pending }).distinct()
        data.edit().putString(PENDING, keep.joinToString(",")).apply()
    }

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences,
    ) {
        draw(context, appWidgetManager, appWidgetIds, widgetData)
        appWidgetManager.notifyAppWidgetViewDataChanged(appWidgetIds, R.id.widget_list)

        val server = widgetData.getString("kasita_server", null)
        val hid = widgetData.getString("kasita_hid", null)
        val key = widgetData.getString("kasita_key", null)
        if (server.isNullOrEmpty() || hid.isNullOrEmpty() || key.isNullOrEmpty()) return

        val pending = goAsync() // keep the receiver alive while fetching (a few seconds at most)
        Thread {
            try {
                sendPending(widgetData)
                val conn = URL("${server.trimEnd('/')}/api/households/$hid/widget").openConnection() as HttpURLConnection
                conn.connectTimeout = 8000
                conn.readTimeout = 8000
                conn.setRequestProperty("X-Api-Key", key)
                conn.setRequestProperty("Accept", "application/json")
                if (conn.responseCode == 200) {
                    val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    val edit = widgetData.edit()
                        .putString("shopping_title", json.optString("shopping_title", "Shopping list"))
                        .putString("shopping", json.optString("shopping", ""))
                        .putString("soon", json.optString("soon", ""))
                    json.optJSONArray("items")?.let { fresh ->
                        // still-unsent ticks stay off the list
                        val unsent = (widgetData.getString(PENDING, "") ?: "").split(',').toSet()
                        val shown = JSONArray()
                        for (i in 0 until fresh.length()) {
                            val o = fresh.getJSONObject(i)
                            if (o.optString("id") !in unsent) shown.put(o)
                        }
                        edit.putString("items_json", shown.toString())
                    }
                    edit.apply()
                    draw(context, appWidgetManager, appWidgetIds, widgetData)
                    appWidgetManager.notifyAppWidgetViewDataChanged(appWidgetIds, R.id.widget_list)
                }
                conn.disconnect()
            } catch (e: Exception) {
                // offline: keep showing the last data
            } finally {
                pending.finish()
            }
        }.start()
    }
}

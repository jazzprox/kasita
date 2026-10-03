package cw.jazzproxy.kasita

import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import android.widget.RemoteViewsService
import es.antonborri.home_widget.HomeWidgetPlugin
import org.json.JSONObject

/** Rows for the widget's list: one per open shopping item, each ticks itself off when tapped. */
class KasitaWidgetService : RemoteViewsService() {
    override fun onGetViewFactory(intent: Intent): RemoteViewsFactory = Factory(applicationContext)

    private class Factory(private val context: Context) : RemoteViewsFactory {
        private var rows: List<JSONObject> = emptyList()

        override fun onCreate() {}

        override fun onDataSetChanged() {
            val a = KasitaWidgetProvider.items(HomeWidgetPlugin.getData(context))
            rows = (0 until a.length()).map { a.getJSONObject(it) }
        }

        override fun onDestroy() {}

        override fun getCount(): Int = rows.size

        override fun getViewAt(position: Int): RemoteViews {
            val o = rows.getOrNull(position) ?: return loadingView
            val qty = o.optDouble("quantity", 1.0)
            val q = if (qty == 1.0) "" else (if (qty % 1.0 == 0.0) "${qty.toLong()} × " else "$qty × ")
            return RemoteViews(context.packageName, R.layout.kasita_widget_item).apply {
                setTextViewText(R.id.widget_item, "○  $q${o.optString("name")}")
                setOnClickFillInIntent(
                    R.id.widget_item,
                    Intent().putExtra(KasitaWidgetProvider.EXTRA_ITEM, o.optString("id")),
                )
            }
        }

        override fun getLoadingView(): RemoteViews =
            RemoteViews(context.packageName, R.layout.kasita_widget_item)

        private val loadingView get() = getLoadingView()

        override fun getViewTypeCount(): Int = 1

        override fun getItemId(position: Int): Long =
            rows.getOrNull(position)?.optString("id")?.hashCode()?.toLong() ?: position.toLong()

        override fun hasStableIds(): Boolean = true
    }
}

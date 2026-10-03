import 'package:flutter/material.dart' hide Text;
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../main.dart';
import '../models.dart';
import '../widgets.dart';
import '../i18n.dart';

/// Pick a day for a recipe (today .. 4 weeks) and plan it.
Future<void> planRecipe(BuildContext context, Map<String, dynamic> recipe) async {
  final s = Kasita.read(context);
  final now = DateUtils.dateOnly(DateTime.now());
  final d = await showDatePicker(
    context: context,
    initialDate: now,
    firstDate: now,
    lastDate: now.add(const Duration(days: 28)),
    helpText: tr('Plan "${recipe['title']}" for'),
  );
  if (d == null || !context.mounted) return;
  try {
    await s.api.setPlan(s.hid, d.toIso8601String().substring(0, 10), recipeId: recipe['id']);
    if (context.mounted) toast(context, 'Planned for ${dateFmt.format(d)}');
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
}

/// A recipe from a web page: paste (or share) the link; Kasita reads it and matches the pantry.
/// Returns the new recipe's id, or null.
Future<String?> importRecipe(BuildContext context, {String? url}) async {
  final s = Kasita.read(context);
  var link = url;
  if (link == null) {
    final ctl = TextEditingController();
    link = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Recipe from a link'),
        content: TextField(
          controller: ctl,
          autofocus: true,
          keyboardType: TextInputType.url,
          decoration: InputDecoration(hintText: tr('https://…'), helperText: tr('Any recipe page; most sites work')),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Import')),
        ],
      ),
    );
  }
  if (link == null || link.isEmpty || !context.mounted) return null;
  showDialog(
    context: context,
    barrierDismissible: false,
    builder: (_) => const AlertDialog(
      content: Row(
        children: [CircularProgressIndicator(), SizedBox(width: 20), Expanded(child: Text('Reading the recipe…'))],
      ),
    ),
  );
  try {
    final r = await s.api.importRecipe(s.hid, link);
    if (!context.mounted) return null;
    Navigator.of(context).pop();
    final have = (r['ingredients'] as List).where((i) => i['product_id'] != null).length;
    toast(context, 'Imported "${r['title']}": $have of ${(r['ingredients'] as List).length} ingredients are pantry products');
    return r['id'] as String;
  } on ApiException catch (e) {
    if (context.mounted) {
      Navigator.of(context).pop();
      toast(context, e.message, error: true);
    }
    return null;
  }
}

class RecipesScreen extends StatefulWidget {
  const RecipesScreen({super.key});
  @override
  State<RecipesScreen> createState() => _RecipesScreenState();
}

class _RecipesScreenState extends State<RecipesScreen> {
  List<Map<String, dynamic>>? _all;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final r = await s.api.recipes(s.hid);
    if (mounted) setState(() => _all = r);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Recipes')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final id = await importRecipe(context);
          if (id == null || !context.mounted) return;
          _load();
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => RecipeScreen(recipeId: id)));
          if (mounted) _load();
        },
        icon: const Icon(Icons.link),
        label: const Text('From a link'),
      ),
      body: _all == null
          ? const Center(child: CircularProgressIndicator())
          : _all!.isEmpty
          ? const EmptyState(
              icon: Icons.menu_book_outlined,
              title: 'No recipes yet',
              message: 'Import one from a recipe page (From a link), or save one from "What can I cook?" on the Pantry screen.',
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                children: [
                  for (final r in _all!)
                    ListTile(
                      leading: Icon(
                        r['ready'] == true ? Icons.check_circle : Icons.menu_book_outlined,
                        color: r['ready'] == true ? t.colorScheme.primary : null,
                      ),
                      title: Text(r['title']),
                      subtitle: Text(
                        r['ready'] == true
                            ? 'Everything is at home'
                            : 'Missing: ${[for (final i in r['ingredients'] as List)
                                if (i['have'] != true) i['name']].join(', ')}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      trailing: (r['minutes'] ?? 0) > 0 ? Text('${r['minutes']} min') : null,
                      onTap: () async {
                        await Navigator.of(context)
                            .push(MaterialPageRoute(builder: (_) => RecipeScreen(recipeId: r['id'])));
                        if (mounted) _load();
                      },
                    ),
                ],
              ),
            ),
    );
  }
}

class RecipeScreen extends StatefulWidget {
  final String recipeId;
  const RecipeScreen({super.key, required this.recipeId});
  @override
  State<RecipeScreen> createState() => _RecipeScreenState();
}

class _RecipeScreenState extends State<RecipeScreen> {
  Map<String, dynamic>? _r;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final r = await s.api.recipe(s.hid, widget.recipeId);
    if (mounted) setState(() => _r = r);
  }

  /// Confirm what the meal used (amounts in each product's unit), take it out, offer Undo.
  Future<void> _cooked() async {
    final s = Kasita.read(context);
    final ings = [
      for (final i in _r!['ingredients'] as List)
        if (i['product_id'] != null) Map<String, dynamic>.from(i),
    ];
    if (ings.isEmpty) return toast(context, 'None of the ingredients are pantry products');
    final qty = {for (final i in ings) i['product_id'] as String: double.tryParse('${i['quantity']}') ?? 1};
    final ok = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (c) => StatefulBuilder(
        builder: (c, set) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const ListTile(title: Text('What did it use?'), subtitle: Text('Taken out of the pantry')),
              for (final i in ings)
                ListTile(
                  title: Text(i['name']),
                  subtitle: Text('${fmtQty(double.tryParse('${i['in_stock']}') ?? 0)} at home'),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.remove),
                        onPressed: () =>
                            set(() => qty[i['product_id']] = ((qty[i['product_id']]! - 0.5).clamp(0, 999))),
                      ),
                      Text(fmtQty(qty[i['product_id']]!)),
                      IconButton(
                        icon: const Icon(Icons.add),
                        onPressed: () => set(() => qty[i['product_id']] = qty[i['product_id']]! + 0.5),
                      ),
                    ],
                  ),
                ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Take it out')),
              ),
            ],
          ),
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final r = await s.api.cooked(s.hid, widget.recipeId, [
        for (final e in qty.entries)
          if (e.value > 0) {'product_id': e.key, 'quantity': e.value},
      ]);
      s.changed();
      _load();
      if (!mounted) return;
      final events = List<String>.from(r['event_ids'] ?? const []);
      final messenger = ScaffoldMessenger.of(context);
      messenger.showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text(
            (r['short'] as List).isEmpty
                ? 'Enjoy! Taken out of the pantry.'
                : 'Not enough: ${(r['short'] as List).join(', ')}',
          ),
          action: SnackBarAction(
            label: tr('Undo'),
            onPressed: () async {
              await s.api.undoStock(s.hid, events);
              s.changed();
              _load();
            },
          ),
        ),
      );
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _r;
    final t = Theme.of(context);
    final s = Kasita.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(r?['title'] ?? 'Recipe'),
        actions: [
          if (r != null && r['source_url'] != null)
            IconButton(
              tooltip: tr('Open the recipe page'),
              icon: const Icon(Icons.open_in_new),
              onPressed: () => launchUrl(Uri.parse(r['source_url']), mode: LaunchMode.externalApplication),
            ),
          if (r != null)
            IconButton(
              tooltip: tr('Delete'),
              icon: const Icon(Icons.delete_outline),
              onPressed: () async {
                await s.api.deleteRecipe(s.hid, widget.recipeId);
                if (context.mounted) Navigator.pop(context);
              },
            ),
        ],
      ),
      bottomNavigationBar: r == null
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () => planRecipe(context, r),
                        icon: const Icon(Icons.calendar_month_outlined),
                        label: const Text('Plan it'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: _cooked,
                        icon: const Icon(Icons.restaurant),
                        label: const Text('Cooked it'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
      body: r == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if ((r['minutes'] ?? 0) > 0 || r['servings'] != null)
                  Text(
                    [
                      if ((r['minutes'] ?? 0) > 0) '${r['minutes']} minutes',
                      if (r['servings'] != null) '${r['servings']}',
                    ].join(' · '),
                    style: t.textTheme.bodySmall,
                  ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(child: Text('Ingredients', style: t.textTheme.titleMedium)),
                    if ((r['ingredients'] as List).any((i) => i['have'] != true))
                      TextButton.icon(
                        onPressed: () async {
                          try {
                            final added = await s.api.missingToList(s.hid, widget.recipeId);
                            s.changed();
                            if (context.mounted) {
                              toast(context, added.isEmpty ? 'Already on the list' : 'On the list: ${added.join(', ')}');
                            }
                          } on ApiException catch (e) {
                            if (context.mounted) toast(context, e.message, error: true);
                          }
                        },
                        icon: const Icon(Icons.playlist_add),
                        label: const Text('Missing to list'),
                      ),
                  ],
                ),
                for (final i in r['ingredients'] as List)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    leading: Icon(
                      i['have'] == true ? Icons.check_circle : Icons.radio_button_unchecked,
                      color: i['have'] == true ? t.colorScheme.primary : t.colorScheme.outline,
                    ),
                    title: Text(i['amount'] == null ? '${i['name']}' : '${i['amount']} ${i['name']}'),
                    subtitle: Text(i['product_id'] == null ? 'to buy' : (i['have'] == true ? 'at home' : 'ran out')),
                  ),
                const SizedBox(height: 16),
                Text('Steps', style: t.textTheme.titleMedium),
                for (final (n, step) in (r['steps'] as List).indexed)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: CircleAvatar(radius: 12, child: Text('${n + 1}')),
                    title: Text('$step'),
                  ),
              ],
            ),
    );
  }
}

/// The next 7 days: one planned meal per day, and 'add missing to the list'.
class WeekPlanScreen extends StatefulWidget {
  const WeekPlanScreen({super.key});
  @override
  State<WeekPlanScreen> createState() => _WeekPlanScreenState();
}

class _WeekPlanScreenState extends State<WeekPlanScreen> {
  List<Map<String, dynamic>>? _days;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final s = Kasita.read(context);
    final d = await s.api.plan(s.hid);
    if (mounted) setState(() => _days = d);
  }

  /// Ask for a week of dinners built around what's at home and the cheapest known prices; show it with its
  /// price; only "Use this plan" saves anything.
  Future<void> _planWeek() async {
    final s = Kasita.read(context);
    final ctl = TextEditingController();
    final wishes = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Plan my week'),
        content: TextField(
          controller: ctl,
          decoration: InputDecoration(
            labelText: tr('Any wishes? (optional)'),
            helperText: tr('e.g. "fish on Friday", "nothing spicy", "quick on weekdays"'),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Plan 7 days')),
        ],
      ),
    );
    if (wishes == null || !mounted) return;
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => const AlertDialog(
        content: Row(children: [CircularProgressIndicator(), SizedBox(width: 20), Expanded(child: Text('Planning…'))]),
      ),
    );
    Map<String, dynamic> plan;
    try {
      plan = await s.api.planSuggest(s.hid, note: wishes);
    } on ApiException catch (e) {
      if (mounted) {
        Navigator.of(context).pop();
        toast(context, e.message, error: true);
      }
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop();
    final days = plan['days'] as List;
    if (days.isEmpty) return toast(context, 'No plan came back; try again.', error: true);
    final cur = plan['currency'];
    final cost = double.tryParse('${plan['est_cost']}') ?? 0;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (c) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.85,
        builder: (c, scroll) => Column(
          children: [
            ListTile(
              title: Text('$cur ${cost.toStringAsFixed(2)} to buy'),
              subtitle: Text(
                [
                  '${days.length} dinners',
                  if ((plan['unpriced'] ?? 0) > 0) '${plan['unpriced']} item(s) without a known price',
                  if (plan['budget'] != null) 'budget $cur ${double.parse('${plan['budget']}').toStringAsFixed(0)}',
                ].join(' · '),
              ),
            ),
            Expanded(
              child: ListView(
                controller: scroll,
                children: [
                  for (final d in days)
                    ListTile(
                      leading: CircleAvatar(child: Text(dayLetter(DateTime.parse(d['day'])))),
                      title: Text('${d['title']}'),
                      subtitle: Text(
                        [
                          if ((d['uses'] as List).isNotEmpty) 'from home: ${[for (final u in d['uses']) u['name']].join(', ')}',
                          if ((d['buy'] as List).isNotEmpty)
                            'buy: ${[for (final b in d['buy']) '${b['name']}${b['price'] == null ? '' : ' ${double.parse('${b['price']}').toStringAsFixed(2)}'}${b['repeat'] == true ? ' (again)' : ''}'].join(', ')}',
                          if ('${d['why']}'.isNotEmpty) '${d['why']}',
                        ].join('\n'),
                      ),
                      isThreeLine: true,
                    ),
                ],
              ),
            ),
            SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: Row(
                  children: [
                    Expanded(child: OutlinedButton(onPressed: () => Navigator.pop(c, false), child: const Text('Not now'))),
                    const SizedBox(width: 12),
                    Expanded(child: FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Use this plan'))),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final added = await s.api.planApply(s.hid, days);
      s.changed();
      if (mounted) {
        toast(context, added.isEmpty ? 'Plan saved: you have everything' : 'Plan saved; ${added.length} item(s) on the shopping list');
        _load();
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _edit(Map<String, dynamic> day) async {
    final s = Kasita.read(context);
    final recipes = await s.api.recipes(s.hid);
    if (!mounted) return;
    final choice = await showModalBottomSheet<Object>(
      context: context,
      showDragHandle: true,
      builder: (c) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            for (final r in recipes)
              ListTile(
                leading: const Icon(Icons.menu_book_outlined),
                title: Text(r['title']),
                onTap: () => Navigator.pop(c, r),
              ),
            ListTile(
              leading: const Icon(Icons.edit_note),
              title: const Text('A note instead (leftovers, eating out…)'),
              onTap: () => Navigator.pop(c, 'note'),
            ),
            if (day['recipe'] != null || day['note'] != null)
              ListTile(
                leading: const Icon(Icons.clear),
                title: const Text('Clear this day'),
                onTap: () => Navigator.pop(c, 'clear'),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;
    final dayStr = '${day['day']}';
    if (choice == 'clear') {
      await s.api.setPlan(s.hid, dayStr);
    } else if (choice == 'note') {
      final ctl = TextEditingController(text: day['note'] ?? '');
      final note = await showDialog<String>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Note for this day'),
          content: TextField(controller: ctl, autofocus: true),
          actions: [FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Save'))],
        ),
      );
      if (note == null) return;
      await s.api.setPlan(s.hid, dayStr, note: note);
    } else if (choice is Map) {
      await s.api.setPlan(s.hid, dayStr, recipeId: choice['id']);
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Week plan'),
        actions: [
          TextButton.icon(
            onPressed: _planWeek,
            icon: const Icon(Icons.auto_awesome),
            label: const Text('Plan my week'),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final s = Kasita.read(context);
          final added = await s.api.planToShopping(s.hid);
          s.changed();
          if (context.mounted) {
            toast(context, added.isEmpty ? 'You have everything the plan needs' : 'Added: ${added.join(', ')}');
          }
        },
        icon: const Icon(Icons.playlist_add),
        label: const Text('Missing → shopping list'),
      ),
      body: _days == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                for (final d in _days!)
                  ListTile(
                    leading: CircleAvatar(child: Text(dayLetter(DateTime.parse(d['day'])))),
                    title: Text(
                      d['recipe']?['title'] ?? d['note'] ?? 'Nothing planned',
                      style: d['recipe'] == null && d['note'] == null ? TextStyle(color: t.colorScheme.outline) : null,
                    ),
                    subtitle: Text(dateFmtYear.format(DateTime.parse(d['day']))),
                    trailing: d['recipe'] == null
                        ? null
                        : Icon(
                            d['recipe']['ready'] == true ? Icons.check_circle : Icons.shopping_cart_outlined,
                            color: d['recipe']['ready'] == true ? t.colorScheme.primary : Colors.orange.shade800,
                          ),
                    onTap: () => _edit(d),
                  ),
                const SizedBox(height: 90),
              ],
            ),
    );
  }
}

String dayLetter(DateTime d) => const ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'][d.weekday - 1];

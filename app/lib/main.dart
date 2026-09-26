import 'package:flutter/material.dart';

import 'screens/home.dart';
import 'screens/login.dart';
import 'state.dart';

void main() {
  final state = AppState();
  runApp(KasitaApp(state: state));
  state.start();
}

/// Makes [AppState] reachable from any widget via `Kasita.of(context)`.
class Kasita extends InheritedNotifier<AppState> {
  const Kasita({super.key, required AppState state, required super.child}) : super(notifier: state);
  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<Kasita>()!.notifier!;
  static AppState read(BuildContext context) => context.getInheritedWidgetOfExactType<Kasita>()!.notifier!;
}

class KasitaApp extends StatelessWidget {
  final AppState state;
  const KasitaApp({super.key, required this.state});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF2E7D5B); // a kitchen-herb green
    return Kasita(
      state: state,
      child: MaterialApp(
        title: 'Kasita',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorSchemeSeed: seed, useMaterial3: true),
        darkTheme: ThemeData(colorSchemeSeed: seed, brightness: Brightness.dark, useMaterial3: true),
        home: const _Gate(),
      ),
    );
  }
}

class _Gate extends StatelessWidget {
  const _Gate();

  /// An invite link looks like `https://kasita.../#/invite/TOKEN`.
  static String? _inviteToken() {
    final f = Uri.base.fragment;
    return f.startsWith('/invite/') ? f.substring('/invite/'.length) : null;
  }

  @override
  Widget build(BuildContext context) {
    final s = Kasita.of(context);
    if (!s.ready) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final invite = _inviteToken();
    if (!s.api.signedIn || invite != null && s.household == null) return LoginScreen(inviteToken: invite);
    if (s.household == null) return const NoHouseholdScreen();
    return const HomeScreen();
  }
}

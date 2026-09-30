import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:japanese_app/src/db/app_db.dart';
import 'package:japanese_app/src/db/review_repo.dart';
import 'package:japanese_app/src/domain/content/app_content_bundle.dart';
import 'package:japanese_app/src/domain/content/app_content_repository.dart';
import 'package:japanese_app/src/domain/review/review_queue.dart';
import 'package:japanese_app/src/domain/review/review_session_plan.dart';
import 'package:japanese_app/src/domain/review/srs.dart' as srs;
import 'package:japanese_app/src/domain/study/word_study_request.dart';
import 'package:japanese_app/src/presentation/review/review_session_navigation.dart';
import 'package:japanese_app/src/presentation/review/review_session_view_model.dart';
import 'package:japanese_app/src/rust/api/jp.dart' as jp;
import 'package:japanese_app/src/screens/review_session.dart';
import 'package:japanese_app/src/services/audio/study_sound_service.dart';
import 'package:japanese_app/src/theme/study_theme.dart';
import 'package:japanese_app/src/widgets/furigana_text.dart';

const root=String.fromEnvironment('REEL_JOB_ROOT');
const renderPixelRatio=int.fromEnvironment('REEL_PIXEL_RATIO',defaultValue:3);
const imageSuffix=String.fromEnvironment('REEL_IMAGE_SUFFIX',defaultValue:'');

class SuppliedContent implements AppContentRepository {
  SuppliedContent(this.bundle);
  final AppContentBundle bundle;
  @override Future<AppContentBundle> load() async=>bundle;
}
class SnapshotModel extends ChangeNotifier implements ReviewSessionViewModel {
  SnapshotModel(this.item,ResolvedContent content,this.question):currentCard=ReviewSessionCard(
    state:srs.createState(srs.ReviewKind.vocab,'word::example',0),isNew:true,content:content);
  final Map<String,dynamic> item;
  final bool question;
  @override final ReviewSessionCard currentCard;
  @override bool get loading=>false;
  @override bool get done=>false;
  @override bool get hasCards=>true;
  @override bool get fixed=>true;
  @override bool get additional=>false;
  @override List<ReviewSessionCard> get cards=>List.filled(item['total'] as int,currentCard);
  @override int get index=>(item['id'] as int)-1;
  @override bool get isInputPhase=>question;
  @override bool get isRevealPhase=>!question;
  @override ReviewRevealKind get revealKind=>ReviewRevealKind.gaveUp;
  @override ReviewInputMode get inputMode=>ReviewInputMode.speech;
  @override bool get showsReading=>true;
  @override bool get wrongFeedbackActive=>false;
  @override bool get checkingCloud=>false;
  @override bool get listening=>false;
  @override bool get hintUsed=>false;
  @override String get recognized=>'';
  @override String? get attemptFeedback=>null;
  @override int get totalCount=>0;
  @override void configureInputMode(ReviewInputMode mode){}
  @override Future<void> initialize({List<SessionEntry>? fixedEntries,int additionalCards=0,WordStudyRequest? request}) async {}
  @override Future<void> prefetchCurrentSpeech() async {}
  @override dynamic noSuchMethod(Invocation invocation)=>super.noSuchMethod(invocation);
}
class Navigation implements ReviewSessionNavigation {
  @override Future<void> openSettings(BuildContext context) async {}
  @override Future<void> leave(BuildContext context) async {}
}
class SilentSounds extends StudySoundService {
  @override Future<void> play(String asset) async {}
  @override Future<void> dispose() async {}
}
String hira(String text)=>String.fromCharCodes(text.runes.map((c)=>c>=0x30a1&&c<=0x30f6?c-0x60:c));

void main(){
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('production study screens from one supplied lesson',(tester) async {
    final data=jsonDecode(File('$root/render-input.json').readAsStringSync()) as Map<String,dynamic>;
    for(final f in [('Pretendard','assets/fonts/PretendardVariable.ttf'),('Noto Sans JP','assets/fonts/NotoSansJP.ttf')]){
      final loader=FontLoader(f.$1)..addFont(rootBundle.load(f.$2));await loader.load();
    }
    final icons=FontLoader('MaterialIcons')..addFont(Future.value(ByteData.sublistView(File('${const String.fromEnvironment('FLUTTER_ROOT')}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf').readAsBytesSync())));await icons.load();
    await tester.binding.setSurfaceSize(const Size(390,844));tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetDevicePixelRatio);addTearDown(()=>tester.binding.setSurfaceSize(null));
    final database=AppDb.forTesting(NativeDatabase.memory());addTearDown(database.close);
    var rendered=0;
    for(final raw in data['items'] as List){
      final item=Map<String,dynamic>.from(raw as Map);final target=Map<String,dynamic>.from(item['target'] as Map);
      final tokens=(item['tokens'] as List).map((raw){final t=Map<String,dynamic>.from(raw as Map);return jp.JpToken(surface:t['surface'],pos:t['pos'],posDetail1:t['pos_detail1'],base:t['base'],reading:t['reading'],pronunciation:t['pronunciation']);}).toList();
      final bundle=AppContentBundle(contentVersion:'reel-furigana-v1',wordsById:{'word':AppVocabularyWord(id:'word',jp:target['base'],reading:target['base_reading'],difficultyLevel:3,tags:[],jlptLevels:[3],senses:[AppVocabularySense(id:'sense',reading:target['base_reading'],meaningKo:target['ko'],partOfSpeech:target['pos'],difficultyLevel:3)],exampleIds:['example'])},examplesById:{'example':AppVocabularyExample(id:'example',jp:item['ja'],reading:hira(item['reading']),ttsReading:null,ko:item['ko'],contextKo:item['direction'],sourceTitle:'히소히소 릴스',difficultyLevel:3,targets:[AppVocabularyTarget(wordId:'word',senseId:'sense',surface:target['surface'],reading:target['reading'],inflected:target['inflected'],start:target['start'],end:target['end'])])});
      final repository=ReviewRepo(database,contentRepository:SuppliedContent(bundle),analyzeText:(_ ) async=>tokens);
      final resolved=await repository.resolve(srs.ReviewKind.vocab,'word::example');
      expect(resolved,isNotNull,reason:item['uid']);
      final content=resolved!;
      expect(content.furigana,isNotEmpty,reason:item['uid']);
      expect(content.furigana!.map((t)=>t.base).join(),item['ja']);
      final rubyReport=content.furigana!.map((t)=>{'base':t.base,'reading':t.reading}).toList();
      await tester.runAsync(() async=>File('${item['folder']}/furigana.json').writeAsString(jsonEncode({'reading':content.reading,'tokens':rubyReport,'target':target,'source':'app Rust analyze + production ReviewRepo.resolve + FuriganaText','reviewed_overrides':item['reading_override']})));
      for(final question in [true,false]){
        final key=GlobalKey();
        final theme=StudyTheme.light.copyWith(textTheme:StudyTheme.light.textTheme.apply(fontFamilyFallback:const ['Pretendard']),primaryTextTheme:StudyTheme.light.primaryTextTheme.apply(fontFamilyFallback:const ['Pretendard']));
        await tester.pumpWidget(RepaintBoundary(key:key,child:MaterialApp(debugShowCheckedModeBanner:false,theme:theme,home:ReviewSessionPage(key:ValueKey('${item['uid']}-$question'),viewModel:SnapshotModel(item,content,question),navigation:Navigation(),soundService:SilentSounds(),title:'문장 학습'))));
        await tester.pumpAndSettle();expect(tester.takeException(),isNull,reason:'${item['uid']}-$question');
        final main=find.byKey(ValueKey(question?'cloze-furigana':'cloze-answer'));
        final widget=tester.widget<FuriganaText>(main);
        expect(widget.show,isTrue);expect(widget.rubyTokens,isNotEmpty);
        if(question){
          expect(find.byKey(const ValueKey('cloze-blank')),findsOneWidget);
          expect(find.byKey(const ValueKey('cloze-explanation')),findsNothing);
          expect(widget.maskStart,target['start']);expect(widget.maskEnd,target['end']);expect(widget.maskText,isNull);
        }else{
          expect(widget.maskStart,isNull);expect(widget.maskEnd,isNull);
          expect(find.byKey(const ValueKey('cloze-explanation')),findsOneWidget);
          if(target['inflected']==true){
            final element=tester.element(find.byKey(const ValueKey('cloze-surface-form')));
            expect(DefaultTextStyle.of(element).style.fontFamilyFallback,contains('Pretendard'));
          }
        }
        if(item['uid']=='egui-02'){
          final kana=find.descendant(of:main,matching:find.text('かお'));
          final kanji=find.descendant(of:main,matching:find.text('顔'));
          expect(kana,findsOneWidget);expect(kanji,findsOneWidget);
          expect(tester.getRect(kana).bottom,lessThanOrEqualTo(tester.getRect(kanji).top+1));
        }
        final boundary=key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final image=await boundary.toImage(pixelRatio:renderPixelRatio.toDouble());
          expect(image.width,(390*renderPixelRatio).round());expect(image.height,(844*renderPixelRatio).round());
          final bytes=(await image.toByteData(format:ui.ImageByteFormat.png))!.buffer.asUint8List();
          final path='${item['folder']}/${question?'app-question':'app-screen'}$imageSuffix.png';
          final file=File(path);final before=File('${item['folder']}/app-screen-without-furigana.png');
          if(imageSuffix.isEmpty&&!question&&await file.exists()&&!await before.exists())await file.copy(before.path);
          await file.writeAsBytes(bytes);image.dispose();
        });
        rendered++;print('FURIGANA_SCREEN ${item['uid']} ${question?'QUESTION':'ANSWER'}');
      }
    }
    expect(rendered,(data['items'] as List).length*2);await tester.pumpWidget(const SizedBox());
  });
}

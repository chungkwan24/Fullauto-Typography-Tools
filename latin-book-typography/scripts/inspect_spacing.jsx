// Read-only payload for the font profile and the rescue planner. No save, close, recompose or export.
// Returns the document's fonts (with file locations for scripts/font_profile.py) and, for each
// paragraph whose last line holds a single word, a hyphenated fragment, or a fragment plus one
// word (runt candidates), its composed lines in the
// shape scripts/spacing_rescue.py reads. Only those paragraphs' last lines are returned, never
// the whole manuscript. A candidate is evidence to look at, not a verdict.
(function(doc, job, helpers) {
    var MAX_CANDIDATES=50, MAX_LINES=8, MAX_PARAGRAPHS=20000;
    var result={name:doc.name,version:app.version,fonts:[],runtCandidates:[],paragraphsScanned:0,truncated:false};
    var i,j,k;
    function str(v){ try { return String(v); } catch(e) { return null; } }
    function trim(s){ return s.replace(/^\s+|\s+$/g,''); }
    for(i=0;i<doc.fonts.length;i++) {
        var f=doc.fonts[i];
        result.fonts.push({name:f.name,family:f.fontFamily,style:f.fontStyleName,
            status:str(f.status),type:str(f.fontType),location:str(f.location)});
    }
    for(i=0;i<doc.stories.length && !result.truncated;i++) {
        var story=doc.stories[i], paragraphs=story.paragraphs;
        for(j=0;j<paragraphs.length;j++) {
            if(++result.paragraphsScanned>MAX_PARAGRAPHS || result.runtCandidates.length>=MAX_CANDIDATES) {
                result.truncated=true; break;
            }
            var p=paragraphs[j], count=p.lines.length;
            if(count<2) continue;
            var last=trim(String(p.lines[count-1].contents));
            // A last line that starts mid-word (the line above ends without a space) is a hyphenated fragment.
            var fragment=!/\s$/.test(String(p.lines[count-2].contents));
            var words=last==='' ? 0 : last.split(/\s+/).length;
            if(words===0 || words>(fragment ? 2 : 1)) continue;
            var kind=words===1 ? (fragment ? 'fragment' : 'single-word') : 'fragment-plus-word';
            var first=Math.max(0,count-MAX_LINES), lines=[], frame=null, page=null, width=null;
            for(k=first;k<count;k++) lines.push(String(p.lines[k].contents).replace(/[\r\n]+$/,''));
            try {
                frame=p.lines[count-1].parentTextFrames[0];
                var b=frame.geometricBounds; width=b[3]-b[1];
                page=frame.parentPage ? frame.parentPage.name : null;
            } catch(e) {}
            var font=p.appliedFont;
            result.runtCandidates.push({
                id:'story'+story.id+'-p'+j, storyId:story.id, page:page, kind:kind,
                start:p.lines[first].insertionPoints[0].index,
                linesInParagraph:count, linesReturned:count-first, lines:lines,
                font:(font && font.isValid) ? font.name : str(font),
                fontLocation:(font && font.isValid) ? str(font.location) : null,
                pointSize:p.pointSize, leading:str(p.leading),
                kerningMethod:str(p.kerningMethod), tracking:p.tracking,
                justification:str(p.justification), composer:str(p.composer),
                minimumWordSpacing:p.minimumWordSpacing, desiredWordSpacing:p.desiredWordSpacing,
                hyphenation:p.hyphenation, frameWidth:width,
                frameColumns:frame ? frame.textFramePreferences.textColumnCount : null,
                paragraphStyle:p.appliedParagraphStyle.name
            });
        }
    }
    return result;
})

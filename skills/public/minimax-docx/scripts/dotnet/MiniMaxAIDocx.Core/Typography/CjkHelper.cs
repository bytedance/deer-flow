using DocumentFormat.OpenXml.Wordprocessing;

namespace MiniMaxAIDocx.Core.Typography;

/// <summary>
/// CJK mixed typography helpers for East Asian font and paragraph configuration.
/// </summary>
public static class CjkHelper
{
    public const string DefaultSimplifiedChinese = "SimSun";
    public const string DefaultJapanese = "MS Mincho";
    public const string DefaultKorean = "Batang";

    /// <summary>
    /// Sets the East Asia font on run properties.
    /// </summary>
    public static void SetEastAsiaFont(RunProperties rPr, string fontName)
    {
        var fonts = rPr.RunFonts;
        if (fonts == null)
        {
            fonts = new RunFonts();
            rPr.RunFonts = fonts;
        }
        fonts.EastAsia = fontName;
    }

    /// <summary>
    /// Configures CJK-appropriate paragraph properties.
    /// </summary>
    public static void ConfigureCjkParagraph(ParagraphProperties pPr)
    {
        // Enable word wrap for CJK
        pPr.WordWrap = new WordWrap { Val = true };
        // Allow auto space between CJK and Latin/numbers
        pPr.AutoSpaceDE = new AutoSpaceDE { Val = true };
        pPr.AutoSpaceDN = new AutoSpaceDN { Val = true };
    }
}

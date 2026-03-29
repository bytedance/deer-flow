namespace MiniMaxAIDocx.Core.OpenXml;

/// <summary>
/// Conversion utilities between OpenXML measurement units (DXA, EMU, points, half-points).
/// </summary>
public static class UnitConverter
{
    // 1 inch = 1440 DXA = 914400 EMU = 72 pt = 144 half-pt

    public static int InchesToDxa(double inches) => (int)(inches * 1440);
    public static int CmToDxa(double cm) => (int)(cm * 567.0);
    public static int PtToDxa(double pt) => (int)(pt * 20);
    public static long InchesToEmu(double inches) => (long)(inches * 914400);
    public static long CmToEmu(double cm) => (long)(cm * 360000);
    public static int PtToHalfPt(double pt) => (int)(pt * 2);
    public static string FontSizeToSz(double ptSize) => ((int)(ptSize * 2)).ToString();

    public static double DxaToInches(int dxa) => dxa / 1440.0;
    public static double DxaToCm(int dxa) => dxa / 567.0;
    public static double DxaToPt(int dxa) => dxa / 20.0;
    public static double EmuToInches(long emu) => emu / 914400.0;
    public static double EmuToCm(long emu) => emu / 360000.0;
}

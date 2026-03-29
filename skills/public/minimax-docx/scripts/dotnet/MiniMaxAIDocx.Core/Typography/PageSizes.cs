namespace MiniMaxAIDocx.Core.Typography;

public record PageSize(int WidthDxa, int HeightDxa);
public record MarginConfig(int TopDxa, int BottomDxa, int LeftDxa, int RightDxa);

/// <summary>
/// Standard page sizes and margin presets in DXA units.
/// </summary>
public static class PageSizes
{
    public static PageSize Letter => new(12240, 15840);   // 8.5 x 11 inches
    public static PageSize A4 => new(11906, 16838);       // 210 x 297 mm
    public static PageSize Legal => new(12240, 20160);    // 8.5 x 14 inches
    public static PageSize A3 => new(16838, 23811);       // 297 x 420 mm
    public static PageSize A5 => new(8391, 11906);        // 148 x 210 mm

    public static MarginConfig StandardMargins => new(1440, 1440, 1440, 1440);  // 1 inch all
    public static MarginConfig NarrowMargins => new(720, 720, 720, 720);        // 0.5 inch all
    public static MarginConfig WideMargins => new(1440, 1440, 2160, 2160);      // 1" top/bottom, 1.5" left/right
}

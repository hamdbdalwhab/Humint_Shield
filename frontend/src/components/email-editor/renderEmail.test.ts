/** Regression tests for the browser-side email editor helpers. */
import { cleanLegacyBodyHtml, mergeTagsForPreview } from './renderEmail';

describe('cleanLegacyBodyHtml', () => {
  it('restores persisted merge tags and removes editor-only artifacts', () => {
    const html =
      '<p>مرحباً <span data-hs-merge-tag="{{first_name}}" contenteditable="false" class="hs-selected">الاسم الأول</span></p>' +
      '<div data-hs-block-id="legacy-1" data-hs-editable="legacy" contenteditable="true">نص</div>' +
      '<script id="hs-editor-bridge">void 0</script>';

    const cleaned = cleanLegacyBodyHtml(html);

    expect(cleaned).toContain('{{first_name}}');
    expect(cleaned).not.toContain('data-hs-merge-tag');
    expect(cleaned).not.toContain('contenteditable');
    expect(cleaned).not.toContain('data-hs-block-id');
    expect(cleaned).not.toContain('data-hs-editable');
    expect(cleaned).not.toContain('hs-selected');
    expect(cleaned).not.toContain('hs-editor-bridge');
  });
});

describe('mergeTagsForPreview', () => {
  it('shows human labels while retaining the persisted token in metadata', () => {
    const html = mergeTagsForPreview('<p>مرحباً {{first_name}}</p>');
    expect(html).toContain('data-hs-merge-tag="{{first_name}}"');
    expect(html).toContain('الاسم الأول');
    expect(html).not.toContain('{{first_name}}</p>');
  });
});

from lrcup import LRCLib

lrclib = LRCLib()

# Şarkıyı ara
results = lrclib.search(
    track="TARKAN feat BÜLENT ERSOY ( BİR BEN BİR ALLAH BİLİYOR )",)

if results:
    first = results[0]
    # Zaman etiketli senkron sözler:
    print(first.syncedLyrics)
    # Çoğu LRCLIB kaydında düz söz alanı da bulunuyor (plainLyrics).
    # print(first.plainLyrics)
else:
    print("Şarkı bulunamadı")
